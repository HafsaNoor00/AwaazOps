"""Database layer for AwaazOps (SQLite for the MVP, PostgreSQL in production).

Data belongs to a fictional company, "Noor Textiles", for demo purposes.
"""

import datetime as dt
import sqlite3

DB_PATH = "awaazops.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY,
    buyer TEXT NOT NULL,
    product TEXT NOT NULL,
    cartons_ordered INTEGER NOT NULL,
    due_date TEXT NOT NULL            -- YYYY-MM-DD
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    reported_by TEXT,
    event_type TEXT NOT NULL,         -- loaded, dispatched, delayed, damaged, other
    order_id INTEGER,
    truck_id TEXT,
    cartons INTEGER,
    note TEXT,
    raw_text TEXT,
    status TEXT NOT NULL DEFAULT 'confirmed'   -- confirmed, pending, rejected
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    order_id INTEGER,
    severity TEXT NOT NULL,           -- high, medium, low
    message TEXT NOT NULL
);
"""

# Plain-English schema the LLM sees for "ask your data" questions.
SCHEMA_FOR_LLM = """Tables (SQLite):
orders(order_id INTEGER, buyer TEXT, product TEXT, cartons_ordered INTEGER, due_date TEXT 'YYYY-MM-DD')
events(id, created_at TEXT 'YYYY-MM-DD HH:MM', reported_by TEXT, event_type TEXT one of
       'loaded','dispatched','delayed','damaged','other', order_id INTEGER, truck_id TEXT,
       cartons INTEGER, note TEXT, status TEXT 'confirmed'|'pending'|'rejected')
Only events with status='confirmed' count.
alerts(id, created_at TEXT, order_id INTEGER, severity TEXT 'high'|'medium'|'low', message TEXT)
Cartons loaded for an order = SUM(events.cartons) WHERE event_type='loaded' AND status='confirmed'.
An order is dispatched if it has an event with event_type='dispatched'."""


def connect(readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    else:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def init_db(reset: bool = False) -> None:
    conn = connect()
    if reset:
        conn.executescript("DROP TABLE IF EXISTS orders; DROP TABLE IF EXISTS events; DROP TABLE IF EXISTS alerts;")
    conn.executescript(SCHEMA)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(events)")]
    if "status" not in cols:  # migrate databases created before the review queue existed
        conn.execute("ALTER TABLE events ADD COLUMN status TEXT NOT NULL DEFAULT 'confirmed'")
    if conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0:
        today = dt.date.today()
        d = lambda days: (today + dt.timedelta(days=days)).isoformat()  # noqa: E731
        conn.executemany(
            "INSERT INTO orders VALUES (?,?,?,?,?)",
            [
                (551, "Nordic Home GmbH", "Cotton bed sheets", 500, d(1)),
                (552, "Atlas Retail UK", "Bath towels", 300, d(3)),
                (553, "Maple Linens CA", "Pillow covers", 450, d(-1)),
                (554, "Sunrise Hotels UAE", "Bathrobes", 200, d(5)),
                (555, "Coastal Living US", "Denim fabric rolls", 120, d(2)),
            ],
        )
        conn.executemany(
            "INSERT INTO events (created_at, reported_by, event_type, order_id, truck_id, cartons, note, raw_text) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [
                (now(), "Bilal (loading bay)", "loaded", 551, "TRK-2", 200, "First batch loaded", "seed"),
                (now(), "Bilal (loading bay)", "loaded", 552, "TRK-1", 300, "Full order loaded", "seed"),
                (now(), "Bilal (loading bay)", "dispatched", 552, "TRK-1", None, "Left for port", "seed"),
                (now(), "Asad (warehouse)", "loaded", 553, "TRK-3", 150, "Partial load", "seed"),
            ],
        )
    conn.commit()
    conn.close()


def get_order(order_id: int):
    with connect() as conn:
        return conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()


def loaded_cartons(order_id: int) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(cartons), 0) FROM events WHERE order_id = ? AND event_type = 'loaded' AND status = 'confirmed'",
            (order_id,),
        ).fetchone()
        return int(row[0])


def add_event(e: dict, reported_by: str, raw_text: str, status: str = "confirmed") -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO events (created_at, reported_by, event_type, order_id, truck_id, cartons, note, raw_text, status) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (now(), reported_by, e["event_type"], e.get("order_id"), e.get("truck_id"),
             e.get("cartons"), e.get("note"), raw_text, status),
        )


def pending_events() -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM events WHERE status = 'pending' ORDER BY id")]


def set_event_status(event_id: int, status: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE events SET status = ? WHERE id = ?", (status, event_id))


def add_alert(order_id, severity: str, message: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO alerts (created_at, order_id, severity, message) VALUES (?,?,?,?)",
            (now(), order_id, severity, message),
        )


def order_board() -> list[dict]:
    """Orders with loaded totals and a computed status."""
    today = dt.date.today().isoformat()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT o.order_id, o.buyer, o.product, o.cartons_ordered, o.due_date,
                   COALESCE(SUM(CASE WHEN e.event_type='loaded' THEN e.cartons END), 0) AS loaded,
                   MAX(CASE WHEN e.event_type='dispatched' THEN 1 ELSE 0 END) AS dispatched,
                   MAX(CASE WHEN e.event_type='delayed' THEN 1 ELSE 0 END) AS delayed
            FROM orders o LEFT JOIN events e ON e.order_id = o.order_id AND e.status = 'confirmed'
            GROUP BY o.order_id ORDER BY o.due_date
            """
        ).fetchall()
    board = []
    for r in rows:
        r = dict(r)
        days_left = (dt.date.fromisoformat(r["due_date"]) - dt.date.fromisoformat(today)).days
        if r["dispatched"]:
            status = "Dispatched"
        elif days_left < 0:
            status = "Late"
        elif r["delayed"] or (days_left <= 2 and r["loaded"] < r["cartons_ordered"]):
            status = "At risk"
        else:
            status = "On track"
        r["progress"] = f"{r['loaded']}/{r['cartons_ordered']}"
        r["status"] = status
        board.append(r)
    return board


def recent(table: str, limit: int = 10) -> list[dict]:
    assert table in ("events", "alerts")
    with connect() as conn:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (limit,))]


def run_readonly_query(sql: str) -> list[dict]:
    with connect(readonly=True) as conn:
        return [dict(r) for r in conn.execute(sql).fetchall()]
