import pytest

from database import db
from database.db import init_db, get_connection


def test_database_tables_exist():
    init_db()

    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row["name"] for row in cursor.fetchall()}

    assert {"tasks", "agent_trace", "calendar_events", "settings",
            "usage_log"} <= tables
    assert not {"schedule_blocks", "change_log"} & tables


def test_tasks_table_accepts_task():
    init_db()

    with get_connection() as conn:
        conn.execute(
            "INSERT INTO tasks (title, remaining_minutes) VALUES (?, ?)",
            ("Study calculus", 60),
        )

        task = conn.execute(
            "SELECT * FROM tasks WHERE title = ?",
            ("Study calculus",),
        ).fetchone()

    assert task is not None
    assert task["remaining_minutes"] == 60
    assert task["status"] == "pending"


def test_task_helpers():
    task = db.create_task("Essay", 240, deadline="2026-10-16T23:59:00")

    assert task["remaining_minutes"] == 240
    assert [t["id"] for t in db.get_tasks()] == [task["id"]]

    db.update_task(task["id"], status="completed")
    assert db.get_tasks() == []
    assert len(db.get_tasks(include_completed=True)) == 1

    db.delete_task(task["id"])
    assert db.get_tasks(include_completed=True) == []


def test_update_task_rejects_unknown_fields():
    task = db.create_task("Essay", 60)

    with pytest.raises(ValueError):
        db.update_task(task["id"], id=5)


def test_session_db_holds_data_but_usage_stays_shared(tmp_path):
    db.use_session_db(tmp_path / "visitor.db")
    db.init_db()
    db.create_task("Visitor task", 60)
    db.add_usage("2026-10-11", "visitor", messages=1)

    db.use_session_db(None)
    assert db.get_tasks() == []  # the task is in the visitor's database
    assert db.get_usage("2026-10-11")["messages"] == 1  # usage is shared


def test_settings_round_trip():
    db.set_setting("template", {"name": "vacation"})

    assert db.get_setting("template") == {"name": "vacation"}
    assert db.get_setting("missing", "default") == "default"
