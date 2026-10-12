import pytest

from agent import task_actions
from database import db


def test_add_task():
    task = task_actions.add_task("Lab report", 120, "2026-10-15", priority=2)

    assert task["remaining_minutes"] == 120
    assert task["deadline"].startswith("2026-10-15T23:59")
    assert task["status"] == "pending"
    assert task["priority"] == 2


@pytest.mark.parametrize("kwargs", [
    {"title": " ", "remaining_minutes": 60},
    {"title": "Essay", "remaining_minutes": 0},
    {"title": "Essay", "remaining_minutes": -5},
    {"title": "Essay", "remaining_minutes": 60, "priority": 9},
])
def test_add_task_validates_fields(kwargs):
    with pytest.raises(ValueError):
        task_actions.add_task(**kwargs)
    assert db.get_tasks() == []


def test_edit_remaining_minutes_is_exact():
    task = task_actions.add_task("Essay", 240)

    updated = task_actions.edit_task(task["id"], remaining_minutes=60)

    assert updated["remaining_minutes"] == 60


def test_edit_remaining_to_zero_completes_and_back_reopens():
    task = task_actions.add_task("Essay", 240)

    done = task_actions.edit_task(task["id"], remaining_minutes=0)
    reopened = task_actions.edit_task(task["id"], remaining_minutes=30)

    assert done["status"] == "completed"
    assert reopened["status"] == "pending"


def test_edit_title_deadline_and_priority():
    task = task_actions.add_task("Essay", 60)

    task_actions.edit_task(task["id"], title="History essay",
                           deadline="2026-10-18 17:00", priority=1)

    updated = db.get_task(task["id"])
    assert updated["title"] == "History essay"
    assert updated["deadline"].startswith("2026-10-18T17:00")
    assert updated["priority"] == 1


def test_edit_rejects_unknown_fields_and_tasks():
    task = task_actions.add_task("Essay", 60)

    with pytest.raises(ValueError):
        task_actions.edit_task(task["id"], status="completed")
    with pytest.raises(ValueError):
        task_actions.edit_task(999, title="x")


def test_complete_and_delete():
    keep = task_actions.add_task("Keep", 60)
    done = task_actions.add_task("Done", 60)
    gone = task_actions.add_task("Gone", 60)

    task_actions.complete_task(done["id"])
    task_actions.delete_task(gone["id"])

    assert [t["id"] for t in db.get_tasks()] == [keep["id"]]
    assert db.get_task(done["id"])["status"] == "completed"
    assert db.get_task(gone["id"]) is None
