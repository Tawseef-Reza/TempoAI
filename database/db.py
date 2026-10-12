import json
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "tempo.db"

TASK_FIELDS = {"title", "priority", "deadline", "remaining_minutes", "status"}

# The web app gives each visitor their own database (tasks, calendar,
# settings). AI usage always goes to the shared DB_PATH so the limits
# count every visitor. The CLI never sets this and uses DB_PATH for all.
_session_db = ContextVar("session_db", default=None)


def use_session_db(path):
    _session_db.set(Path(path) if path else None)


def sessions_dir():
    return DB_PATH.parent / "sessions"


@contextmanager
def get_connection(shared=False):
    """Use as `with get_connection() as conn:`. Commits on success, rolls
    back on error, and always closes (an open connection keeps the file
    locked on Windows)."""
    path = DB_PATH if shared else (_session_db.get() or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db():
    _create_tables(shared=False)
    if _session_db.get() is not None:
        _create_tables(shared=True)


def _create_tables(shared):
    with get_connection(shared) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                priority INTEGER DEFAULT 3,
                deadline TEXT,
                remaining_minutes INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'completed')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS agent_trace (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                tool TEXT,
                arguments TEXT,
                result TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            -- The local calendar: fixed events of the loaded month plus
            -- TempoAI's blocks (editable = 1, linked to a task).
            CREATE TABLE IF NOT EXISTS calendar_events (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                start TEXT NOT NULL,
                end TEXT NOT NULL,
                editable INTEGER NOT NULL DEFAULT 0,
                all_day INTEGER NOT NULL DEFAULT 0,
                task_id INTEGER
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            -- AI usage per real day and user, for the usage limits.
            CREATE TABLE IF NOT EXISTS usage_log (
                day TEXT NOT NULL,
                user_key TEXT NOT NULL,
                messages INTEGER NOT NULL DEFAULT 0,
                cost_usd REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (day, user_key)
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_status
                ON tasks(status);

            CREATE INDEX IF NOT EXISTS idx_calendar_events_start
                ON calendar_events(start);
        """)


# ---------- tasks ----------

def create_task(title, remaining_minutes, deadline=None, priority=3):
    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO tasks (title, priority, deadline, remaining_minutes)
            VALUES (?, ?, ?, ?)
        """, (title, priority, deadline, remaining_minutes))
        return get_task(cursor.lastrowid, conn)


def get_task(task_id, conn=None):
    if conn is None:
        with get_connection() as conn:
            return get_task(task_id, conn)
    row = conn.execute(
        "SELECT * FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    return dict(row) if row else None


def get_tasks(include_completed=False):
    query = "SELECT * FROM tasks"
    if not include_completed:
        query += " WHERE status != 'completed'"
    query += " ORDER BY id"
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(query)]


def update_task(task_id, **fields):
    unknown = set(fields) - TASK_FIELDS
    if unknown:
        raise ValueError(f"Unknown task fields: {sorted(unknown)}")
    if not fields:
        return get_task(task_id)

    assignments = ", ".join(f"{name} = ?" for name in fields)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE tasks SET {assignments}, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (*fields.values(), task_id),
        )
        return get_task(task_id, conn)


def delete_task(task_id):
    """Remove a task (its calendar blocks are removed by the next applied
    plan)."""
    with get_connection() as conn:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))


# ---------- agent trace ----------

def _json(value):
    return json.dumps(value, default=str) if value is not None else None


def log_trace(action, tool=None, arguments=None, result=None):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO agent_trace (action, tool, arguments, result) "
            "VALUES (?, ?, ?, ?)",
            (action, tool, _json(arguments), _json(result)),
        )


def get_trace(limit=50):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_trace ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


# ---------- AI usage ----------

def add_usage(day, user_key, messages=0, cost_usd=0.0):
    with get_connection(shared=True) as conn:
        conn.execute("""
            INSERT INTO usage_log (day, user_key, messages, cost_usd)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(day, user_key) DO UPDATE SET
                messages = messages + excluded.messages,
                cost_usd = cost_usd + excluded.cost_usd
        """, (day, user_key, messages, cost_usd))


def get_usage(day, user_key=None):
    """Totals for a day: one user's, or everyone's when user_key is None."""
    query = """
        SELECT COALESCE(SUM(messages), 0) AS messages,
               COALESCE(SUM(cost_usd), 0) AS cost_usd
        FROM usage_log WHERE day = ?
    """
    params = [day]
    if user_key is not None:
        query += " AND user_key = ?"
        params.append(user_key)
    with get_connection(shared=True) as conn:
        return dict(conn.execute(query, params).fetchone())


# ---------- settings ----------

def get_setting(key, default=None):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    return json.loads(row["value"]) if row else default


def set_setting(key, value):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )


def get_preferences():
    return get_setting("preferences")


def set_preferences(text):
    set_setting("preferences", text)


if __name__ == "__main__":
    init_db()
    print(f"TempoAI database initialized: {DB_PATH}")
