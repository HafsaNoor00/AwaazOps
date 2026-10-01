"""AwaazOps MVP: Urdu voice control tower for factory loading and dispatch."""

import datetime as dt
import os
import time

import pandas as pd
import streamlit as st
from groq import Groq

import db
from ai import AI, DispatchEvent, check_rules
from eval_set import EVAL_SET

st.set_page_config(page_title="AwaazOps", page_icon="🏭", layout="wide")


def setting(name, default=None):
    try:
        return st.secrets[name]
    except Exception:
        return os.getenv(name, default)


API_KEY = setting("GROQ_API_KEY")
LLM_MODEL = setting("GROQ_MODEL", "openai/gpt-oss-120b")
WHISPER_MODEL = setting("WHISPER_MODEL", "whisper-large-v3")
DEMO_USER, DEMO_PASS = setting("DEMO_USER", "demo"), setting("DEMO_PASS", "demo123")

SAMPLES = {
    "Loaded (Roman Urdu)": "Truck 4 mein order 551 ke teen sau carton load ho gaye hain.",
    "Dispatched short (Roman Urdu)": "Order 553 wala truck TRK-3 nikal gaya hai factory se.",
    "Delay (Roman Urdu)": "Order 555 ka kapra abhi dyeing mein hai, do din late hoga.",
    "Damaged (English)": "20 cartons of order 554 got wet in the rain at the loading bay.",
    "Urdu script": "آرڈر 552 کا ٹرک پورٹ پہنچ گیا ہے، کوئی مسئلہ نہیں۔",
}

# ---------- Login ----------
st.session_state.setdefault("auth", False)
if not st.session_state.auth:
    st.title("🏭 AwaazOps")
    st.caption("Voice-first control tower for factory loading and dispatch")
    with st.form("login"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.form_submit_button("Log in"):
            if u == DEMO_USER and p == DEMO_PASS:
                st.session_state.auth = True
                st.rerun()
            st.error("Wrong username or password.")
    st.info(f"Demo account: **{DEMO_USER}** / **{DEMO_PASS}**")
    st.stop()

if not API_KEY:
    st.error("GROQ_API_KEY is not set. Add it to Streamlit secrets or your environment.")
    st.stop()

db.init_db()
ai = AI(Groq(api_key=API_KEY), LLM_MODEL, WHISPER_MODEL)

# ---------- Header ----------
st.title("🏭 AwaazOps")
st.caption(f"Demo factory: Noor Textiles (fictional) · LLM: {LLM_MODEL} · Speech: {WHISPER_MODEL}")

with st.sidebar:
    reporter = st.selectbox("Reporting as", ["Bilal (loading bay)", "Asad (warehouse)", "Sana (dispatch desk)"])
    if st.button("Reset demo data"):
        db.init_db(reset=True)
        st.rerun()
    if st.button("Log out"):
        st.session_state.auth = False
        st.rerun()

tab_report, tab_board, tab_ask, tab_eval = st.tabs(
    ["🎙️ Floor update", "📊 Control tower", "💬 Ask your data", "🧪 Evaluation"]
)


def open_orders_text() -> str:
    return "\n".join(
        f"- order {o['order_id']}: {o['product']} for {o['buyer']}, {o['cartons_ordered']} cartons, due {o['due_date']}"
        for o in db.order_board()
    )


# ---------- Tab 1: floor update ----------
with tab_report:
    st.write("Supervisors send updates the way they already do: a quick **voice note** or message in Urdu or English.")
    audio = st.audio_input("Record a voice note") if hasattr(st, "audio_input") else None
    uploaded = st.file_uploader("…or upload a voice note", type=["wav", "mp3", "m4a", "ogg", "webm"])
    sample = st.selectbox("…or try a sample message", ["(type your own)"] + list(SAMPLES))
    text = st.text_area("Message", value="" if sample == "(type your own)" else SAMPLES[sample], height=90)

    if st.button("Process update", type="primary"):
        try:
            source = audio or uploaded
            if source is not None:
                with st.spinner("Transcribing voice note..."):
                    text = ai.transcribe(source.getvalue(), getattr(source, "name", None) or "note.wav")
                st.info(f"**Transcript:** {text}")
            if not text.strip():
                st.warning("Record, upload or type an update first.")
                st.stop()

            with st.spinner("Understanding the update..."):
                event = ai.extract_event(text, open_orders_text())
        except Exception as e:
            st.error(f"AI service error: {e}")
            st.stop()

        if event is None:
            db.add_alert(None, "medium", f"Could not understand update from {reporter}: {text[:120]}")
            st.error("Could not turn this message into a valid event. It was sent to a supervisor for review.")
            st.stop()

        order = db.get_order(event.order_id) if event.order_id else None
        needs_review = event.confidence < 0.7

        if event.order_id is not None and order is None:
            alerts = [("high", f"Order {event.order_id} does not exist")]
        elif needs_review:
            # Human-in-the-loop: unsure extractions wait for a supervisor instead of changing the data.
            db.add_event(event.model_dump(), reporter, text, status="pending")
            alerts = [("medium", f"Low confidence ({event.confidence:.0%}): waiting for supervisor approval")]
        else:
            loaded_before = db.loaded_cartons(event.order_id) if order else 0
            alerts = check_rules(event, order, loaded_before)
            db.add_event(event.model_dump(), reporter, text)
        for severity, message in alerts:
            db.add_alert(event.order_id, severity, message)

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Event", event.event_type)
        c2.metric("Order", event.order_id or "?")
        c3.metric("Truck", event.truck_id or "-")
        c4.metric("Cartons", event.cartons if event.cartons is not None else "-")
        c5.metric("Confidence", f"{event.confidence:.0%}")
        st.write(f"**Summary:** {event.note}")
        if alerts:
            for severity, message in alerts:
                (st.error if severity == "high" else st.warning)(f"**{severity.upper()} alert:** {message}")
        else:
            st.success("Saved. No problems found.")

# ---------- Tab 2: control tower ----------
with tab_board:
    board = pd.DataFrame(db.order_board())
    if not board.empty:
        k1, k2, k3, k4 = st.columns(4)
        for col, label in zip((k1, k2, k3, k4), ("On track", "At risk", "Late", "Dispatched")):
            col.metric(label, int((board["status"] == label).sum()))

        # --- AI shift briefing agent ---
        if st.button("🧠 Generate shift briefing", type="primary"):
            with st.spinner("The agent is reviewing every order and alert..."):
                try:
                    st.session_state.briefing = ai.shift_briefing(
                        db.order_board(), db.recent("alerts", 15), dt.date.today().isoformat()
                    )
                except Exception as e:
                    st.error(f"AI service error: {e}")
        brief = st.session_state.get("briefing")
        if brief:
            with st.container(border=True):
                st.markdown(f"#### {brief.headline}")
                for r in brief.risks:
                    icon = {"high": "🔴", "medium": "🟠", "low": "🟡"}[r.severity]
                    order_txt = f"Order {r.order_id}: " if r.order_id else ""
                    st.markdown(f"{icon} **{order_txt}{r.issue}**  \n➡️ {r.action}")
                if brief.good_news:
                    st.markdown(f"✅ {brief.good_news}")

        st.subheader("Orders")
        board["loaded_pct"] = (board["loaded"] / board["cartons_ordered"] * 100).clip(upper=100)
        st.dataframe(
            board[["order_id", "buyer", "product", "progress", "loaded_pct", "due_date", "status"]],
            hide_index=True, width="stretch",
            column_config={"loaded_pct": st.column_config.ProgressColumn(
                "Loaded", min_value=0, max_value=100, format="%d%%")},
        )

    # --- Human approval queue ---
    pending = db.pending_events()
    st.subheader(f"Supervisor approval queue ({len(pending)})")
    if not pending:
        st.caption("Nothing waiting. Updates the AI was unsure about appear here before they change any data.")
    for p in pending:
        with st.container(border=True):
            st.write(f"**{p['reported_by']}** said: _{p['raw_text']}_")
            st.write(f"AI read it as: **{p['event_type']}**, order **{p['order_id']}**, "
                     f"truck **{p['truck_id'] or '-'}**, cartons **{p['cartons'] if p['cartons'] is not None else '-'}**")
            a, b, _ = st.columns([1, 1, 4])
            if a.button("✅ Approve", key=f"ok{p['id']}"):
                ev = DispatchEvent(event_type=p["event_type"], order_id=p["order_id"], truck_id=p["truck_id"],
                                   cartons=p["cartons"], note=p["note"] or "", confidence=1.0)
                order = db.get_order(ev.order_id) if ev.order_id else None
                before = db.loaded_cartons(ev.order_id) if order else 0
                for severity, message in check_rules(ev, order, before):
                    db.add_alert(ev.order_id, severity, message)
                db.set_event_status(p["id"], "confirmed")
                st.rerun()
            if b.button("❌ Reject", key=f"no{p['id']}"):
                db.set_event_status(p["id"], "rejected")
                st.rerun()
    left, right = st.columns(2)
    with left:
        st.subheader("Latest alerts")
        alerts = db.recent("alerts")
        if alerts:
            st.dataframe(pd.DataFrame(alerts)[["created_at", "severity", "order_id", "message"]],
                         hide_index=True, width="stretch")
        else:
            st.caption("No alerts yet.")
    with right:
        st.subheader("Latest floor events")
        st.dataframe(
            pd.DataFrame(db.recent("events"))[["created_at", "reported_by", "event_type", "order_id", "truck_id", "cartons", "status"]],
            hide_index=True, width="stretch",
        )

# ---------- Tab 3: ask your data ----------
with tab_ask:
    st.write("Managers ask questions in plain English or Urdu. The AI writes a **read-only** SQL query, which is safety-checked before it runs.")
    examples = [
        "Which orders are not dispatched yet and due in the next 3 days?",
        "How many cartons have been loaded for each order?",
        "Show all high severity alerts.",
        "Konsa order late hai?",
    ]
    q = st.selectbox("Example questions", ["(type your own)"] + examples)
    question = st.text_input("Your question", value="" if q == "(type your own)" else q)
    if st.button("Ask") and question.strip():
        try:
            with st.spinner("Writing the query..."):
                sql = ai.question_to_sql(question, db.SCHEMA_FOR_LLM, dt.date.today().isoformat())
            rows = db.run_readonly_query(sql)
            with st.spinner("Summarizing..."):
                answer = ai.summarize_answer(question, rows)
            st.success(answer or "Done.")
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            with st.expander("SQL used"):
                st.code(sql, language="sql")
        except ValueError as e:
            st.error(f"Blocked: {e}")
        except Exception as e:
            st.error(f"Could not answer that question: {e}")

# ---------- Tab 4: evaluation ----------
with tab_eval:
    st.write(
        f"How accurate is the AI? This runs the extractor on **{len(EVAL_SET)} labelled floor messages** "
        "(Roman Urdu, Urdu script and English) and compares its output with the correct answers."
    )
    with st.expander("See the labelled test set"):
        st.dataframe(pd.DataFrame(EVAL_SET), hide_index=True, width="stretch")
    if st.button("Run evaluation", type="primary"):
        orders_ctx, rows = open_orders_text(), []
        progress = st.progress(0.0, text="Evaluating...")
        for i, item in enumerate(EVAL_SET):
            t0 = time.time()
            try:
                ev = ai.extract_event(item["text"], orders_ctx)
            except Exception:
                ev = None
            latency = time.time() - t0
            got = ev.model_dump() if ev else {"event_type": None, "order_id": None, "cartons": None}
            checks = {f: got.get(f) == item[f] for f in ("event_type", "order_id", "cartons")}
            rows.append({
                "message": item["text"],
                "expected": f"{item['event_type']} / {item['order_id']} / {item['cartons']}",
                "got": f"{got.get('event_type')} / {got.get('order_id')} / {got.get('cartons')}",
                **{f"{k}_ok": v for k, v in checks.items()},
                "all_correct": all(checks.values()),
                "latency_s": round(latency, 2),
            })
            progress.progress((i + 1) / len(EVAL_SET), text=f"Evaluating {i + 1}/{len(EVAL_SET)}")
            time.sleep(0.3)  # stay under free-tier rate limits
        st.session_state.eval_results = pd.DataFrame(rows)

    res = st.session_state.get("eval_results")
    if res is not None:
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Fully correct", f"{res['all_correct'].mean():.0%}")
        m2.metric("Event type", f"{res['event_type_ok'].mean():.0%}")
        m3.metric("Order number", f"{res['order_id_ok'].mean():.0%}")
        m4.metric("Cartons", f"{res['cartons_ok'].mean():.0%}")
        m5.metric("Avg latency", f"{res['latency_s'].mean():.1f} s")
        st.subheader("Mistakes")
        wrong = res[~res["all_correct"]]
        if wrong.empty:
            st.success("No mistakes on this test set.")
        else:
            st.dataframe(wrong[["message", "expected", "got"]], hide_index=True, width="stretch")
