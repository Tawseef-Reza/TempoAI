"""Manual task actions: the only way tasks change.

These run immediately, never call the AI, and never touch the calendar.
The next plan simply uses the tasks as they are.
"""

from datetime import datetime, time

from database import db
from scheduling.scheduler import to_local

EDITABLE_FIELDS = {"title", "deadline", "priority", "remaining_minutes"}


def parse_deadline(value):
    """Accept '2026-10-15 23:59', '2026-10-15T23:59' or '2026-10-15'
    (end of that day). Returns an ISO string, or None for no deadline."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    parsed = datetime.fromisoformat(text)
    if len(text) <= 10:  # date only
        parsed = datetime.combine(parsed.date(), time(23, 59))
    return to_local(parsed).isoformat(timespec="minutes")


def _minutes(value):
    minutes = int(value)
    if minutes < 0:
        raise ValueError("Minutes can't be negative.")
    return minutes


def _priority(value):
    priority = int(value)
    if not 1 <= priority <= 5:
        raise ValueError("Priority must be 1 (highest) to 5 (lowest).")
    return priority


def _get(task_id):
    task = db.get_task(int(task_id))
    if task is None:
        raise ValueError(f"No task with id {task_id}.")
    return task


def add_task(title, remaining_minutes, deadline=None, priority=3):
    title = str(title).strip()
    if not title:
        raise ValueError("A task needs a title.")
    minutes = _minutes(remaining_minutes)
    if minutes == 0:
        raise ValueError("A new task needs some minutes of work.")
    return db.create_task(
        title, minutes, deadline=parse_deadline(deadline),
        priority=_priority(priority),
    )


def edit_task(task_id, **fields):
    task = _get(task_id)
    unknown = set(fields) - EDITABLE_FIELDS
    if unknown:
        raise ValueError(
            f"Can't edit {sorted(unknown)}. "
            f"Editable: {sorted(EDITABLE_FIELDS)}."
        )

    updates = {}
    if "title" in fields:
        title = str(fields["title"]).strip()
        if not title:
            raise ValueError("A task needs a title.")
        updates["title"] = title
    if "deadline" in fields:
        updates["deadline"] = parse_deadline(fields["deadline"])
    if "priority" in fields:
        updates["priority"] = _priority(fields["priority"])
    if "remaining_minutes" in fields:
        minutes = _minutes(fields["remaining_minutes"])
        updates["remaining_minutes"] = minutes
        updates["status"] = "completed" if minutes == 0 else "pending"
    return db.update_task(task["id"], **updates)


def complete_task(task_id):
    task = _get(task_id)
    return db.update_task(task["id"], remaining_minutes=0,
                          status="completed")


def delete_task(task_id):
    task = _get(task_id)
    db.delete_task(task["id"])
    return task


def set_preferences(text):
    """Standing scheduling preferences in plain words (e.g. "no work before
    10am"). Shown to the AI on every request. Empty text clears them."""
    text = (text or "").strip()
    db.set_preferences(text or None)
    return text
