# AwaazOps

A voice-first control tower for factory loading and dispatch. Floor supervisors send quick voice notes or messages in Urdu, Roman Urdu or English ("Truck 4 mein order 551 ke 300 carton load ho gaye"). AwaazOps turns them into structured events, checks each one against the order, alerts managers about problems (short dispatches, over-loading, delays, damage), and lets managers ask questions about their operations in plain language.

**Live demo:** _add your Streamlit link here_ · login `App` / `APP123`

## How it works
1. **Speech to text:** Whisper large-v3 (open-source) transcribes the voice note.
2. **Event extraction:** an open-weight GPT-OSS model turns the message into JSON (event type, order, truck, cartons, confidence), validated with Pydantic and retried once if invalid.
3. **Human approval queue:** if the AI's confidence is below 70%, the update does not touch the data. It waits for a supervisor to approve or reject it.
4. **Business rules:** plain Python, not the LLM, decides alerts: dispatched short, over-loaded, unknown order, delay, damage.
5. **Control tower:** live order board with status (on track, at risk, late, dispatched) and loading progress, alerts and floor events.
6. **Shift briefing agent:** reads every order and alert and writes the top risks, each with one concrete next action.
7. **Ask your data:** the LLM writes a SQL query; a guardrail allows only a single read-only SELECT, which runs on a read-only database connection.
8. **Evaluation:** a labelled set of 20 floor messages (Roman Urdu, Urdu script, English) measures extraction accuracy per field and latency, and lists every mistake.

See `architecture.mmd` for the full production architecture.

## Run locally
```bash
pip install -r requirements.txt
mkdir .streamlit && cp secrets.toml.example .streamlit/secrets.toml   # then add your Groq key
streamlit run app.py
```

## Stack
Streamlit · Groq (Whisper large-v3, GPT-OSS 120B) · Pydantic · SQLite (PostgreSQL in production) · pandas

## Roadmap
WhatsApp intake through n8n, FastAPI backend, LangGraph agents, PostgreSQL, Slack/WhatsApp alerts, a larger evaluation set from real floor messages, cost tracking, role-based access.

Demo data belongs to a fictional company, "Noor Textiles".
