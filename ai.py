"""AI layer for AwaazOps: speech-to-text, event extraction, rules, and text-to-SQL.

Models are open-weight (Whisper, GPT-OSS) served through Groq's free API for the MVP.
"""

import json
import re
import time
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError


class DispatchEvent(BaseModel):
    event_type: Literal["loaded", "dispatched", "delayed", "damaged", "other"]
    order_id: Optional[int] = None
    truck_id: Optional[str] = None
    cartons: Optional[int] = Field(default=None, ge=0)
    note: str = Field(default="", max_length=300)
    confidence: float = Field(ge=0, le=1)


class Risk(BaseModel):
    order_id: Optional[int] = None
    severity: Literal["high", "medium", "low"]
    issue: str
    action: str


class Briefing(BaseModel):
    headline: str
    risks: list[Risk]
    good_news: str = ""


class AI:
    def __init__(self, client, llm_model: str, whisper_model: str):
        self.client = client
        self.llm_model = llm_model
        self.whisper_model = whisper_model

    # ---------- 1. Speech to text ----------
    def transcribe(self, audio_bytes: bytes, filename: str = "note.wav") -> str:
        result = self.client.audio.transcriptions.create(
            file=(filename, audio_bytes),
            model=self.whisper_model,
            prompt="Factory dispatch update in Urdu or English: order number, truck, cartons, loaded, dispatched.",
        )
        return result.text.strip()

    # ---------- LLM helper ----------
    def _json(self, system: str, user: str, retries: int = 3) -> dict:
        for attempt in range(retries):
            try:
                r = self.client.chat.completions.create(
                    model=self.llm_model,
                    temperature=0,
                    response_format={"type": "json_object"},
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                )
                return json.loads(r.choices[0].message.content)
            except Exception:
                if attempt == retries - 1:
                    raise
                time.sleep(2 * (attempt + 1))
        return {}

    # ---------- 2. Message -> structured event ----------
    EXTRACT_PROMPT = """You turn factory floor updates into structured dispatch events.
Updates may be in Urdu script, Roman Urdu or English. Numbers may be written as words
(e.g. "teen sau" = 300, "پانچ سو" = 500).
Return only a JSON object with keys:
- event_type: "loaded" (cartons put on a truck), "dispatched" (truck left the factory),
  "delayed" (something will be late), "damaged" (goods damaged), or "other"
- order_id: integer order number, or null if not mentioned
- truck_id: truck identifier in the form "TRK-<number>", or null
- cartons: integer number of cartons, or null
- note: short English summary of the update
- confidence: 0 to 1, how sure you are about the extracted fields
Never guess an order number that is not in the message."""

    def extract_event(self, text: str, open_orders: str) -> Optional[DispatchEvent]:
        user = f"Open orders for reference:\n{open_orders}\n\nFloor update:\n{text}"
        for _ in range(2):  # one retry on invalid output
            try:
                return DispatchEvent(**self._json(self.EXTRACT_PROMPT, user))
            except (ValidationError, json.JSONDecodeError, TypeError):
                continue
        return None

    # ---------- 3. Ask your data (text-to-SQL) ----------
    SQL_PROMPT = """You write one SQLite SELECT query that answers a manager's question.
{schema}
Today's date is {today}. Use date('now') style functions only if needed.
Return only a JSON object: {{"sql": "<one SELECT statement>"}}"""

    FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum)\b", re.I)

    def question_to_sql(self, question: str, schema: str, today: str) -> str:
        sql = self._json(self.SQL_PROMPT.format(schema=schema, today=today), question).get("sql", "")
        return self.check_sql(sql)

    @classmethod
    def check_sql(cls, sql: str) -> str:
        """Guardrail: only a single read-only SELECT is allowed."""
        sql = sql.strip().rstrip(";").strip()
        if not re.match(r"^(select|with)\b", sql, re.I):
            raise ValueError("Only SELECT queries are allowed.")
        if ";" in sql or cls.FORBIDDEN.search(sql):
            raise ValueError("Query blocked by safety check.")
        if not re.search(r"\blimit\b", sql, re.I):
            sql += " LIMIT 50"
        return sql

    def summarize_answer(self, question: str, rows: list) -> str:
        r = self._json(
            "Answer the manager's question in 1-3 short sentences using only the query results. "
            'Return JSON: {"answer": "..."}',
            f"Question: {question}\nResults (JSON): {json.dumps(rows[:50], default=str)}",
        )
        return r.get("answer", "")


    # ---------- 4. Shift briefing agent ----------
    BRIEFING_PROMPT = """You are an operations analyst for a textile factory's dispatch team.
Today's date is {today}. Read the order board and recent alerts and write a shift briefing.
Prioritise orders that are late, at risk, dispatched short, or have damage or delays.
For each risk give one concrete next action (who should do what), e.g. "Assign a truck and load
the remaining 300 cartons before 6 pm". Use only the data given; never invent orders.
Return only a JSON object: {{"headline": "one sentence", "risks": [{{"order_id": 551,
"severity": "high"|"medium"|"low", "issue": "...", "action": "..."}}], "good_news": "one sentence"}}
List at most 5 risks, most severe first."""

    def shift_briefing(self, board: list, alerts: list, today: str) -> Optional[Briefing]:
        data = json.dumps({"orders": board, "recent_alerts": alerts}, default=str)
        for _ in range(2):
            try:
                return Briefing(**self._json(self.BRIEFING_PROMPT.format(today=today), data))
            except (ValidationError, json.JSONDecodeError, TypeError):
                continue
        return None


# ---------- 5. Business rules (code decides alerts, not the LLM) ----------
def check_rules(event: DispatchEvent, order, loaded_before: int) -> list[tuple[str, str]]:
    """Return a list of (severity, message) alerts for a new event."""
    alerts = []
    if event.confidence < 0.7:
        alerts.append(("medium", f"Low confidence ({event.confidence:.0%}): supervisor should confirm this update"))
    if event.order_id is None:
        alerts.append(("medium", "No order number in the update"))
        return alerts
    if order is None:
        alerts.append(("high", f"Order {event.order_id} does not exist"))
        return alerts

    ordered = order["cartons_ordered"]
    if event.event_type == "loaded" and event.cartons:
        total = loaded_before + event.cartons
        if total > ordered:
            alerts.append(("high", f"Over-loaded: {total} cartons loaded for order {event.order_id}, only {ordered} ordered"))
    if event.event_type == "dispatched" and loaded_before < ordered:
        alerts.append(("high", f"Dispatched short: order {event.order_id} left with {loaded_before} of {ordered} cartons"))
    if event.event_type == "delayed":
        alerts.append(("medium", f"Delay reported for order {event.order_id} (due {order['due_date']}): {event.note}"))
    if event.event_type == "damaged":
        alerts.append(("high", f"Damaged goods reported for order {event.order_id}: {event.note}"))
    return alerts
