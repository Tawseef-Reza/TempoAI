"""TempoAI's calendar, stored in SQLite.

Holds the fixed events of the loaded month plus TempoAI's own blocks.
TempoAI may only move or delete blocks it created.
"""

from datetime import timezone
from uuid import uuid4

from database import db
from scheduling.scheduler import expand_weekly_availability, to_local

# Waking hours used when no month-specific pattern is set.
# Keys are weekdays (0=Mon .. 6=Sun).
DEFAULT_AVAILABILITY = {day: [("08:00", "22:00")] for day in range(7)}


def _stored(value):
    """UTC ISO text, so string comparison in SQL matches time order."""
    return to_local(value).astimezone(timezone.utc).isoformat()


class LocalCalendar:

    def __init__(self):
        db.init_db()

    @property
    def availability_pattern(self):
        pattern = db.get_setting("availability_pattern")
        if not pattern:
            return DEFAULT_AVAILABILITY
        # JSON turns weekday keys into strings and tuples into lists.
        return {
            int(day): [tuple(r) for r in ranges]
            for day, ranges in pattern.items()
        }

    def set_availability_pattern(self, pattern):
        db.set_setting("availability_pattern", pattern)

    def get_availability(self, start_time, end_time):
        """Windows when the user is willing to work, before fixed events
        are subtracted."""
        return expand_weekly_availability(
            self.availability_pattern, start_time, end_time
        )

    def get_events(self, start_time=None, end_time=None):
        query = "SELECT * FROM calendar_events"
        clauses, params = [], []
        if start_time is not None:
            clauses.append("end > ?")
            params.append(_stored(start_time))
        if end_time is not None:
            clauses.append("start < ?")
            params.append(_stored(end_time))
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY start"

        with db.get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_event(row) for row in rows]

    def add_fixed_event(self, title, start, end, all_day=False):
        """Add a fixed commitment (class, shift) TempoAI cannot edit."""
        return self._insert(
            {"title": title, "start": start, "end": end},
            editable=False, all_day=all_day,
        )

    def remove_fixed_event(self, event_id):
        """Remove a fixed commitment. TempoAI blocks go through
        delete_block instead."""
        if self._get(event_id)["editable"]:
            raise PermissionError("That's a TempoAI block, not a fixed event.")
        self._delete(event_id)

    def create_block(self, event):
        return self._insert(event, editable=True, all_day=False)

    def move_block(self, event_id, new_start, new_end):
        self._get_editable(event_id)
        start, end = to_local(new_start), to_local(new_end)
        if end <= start:
            raise ValueError("Event end must be after its start.")

        with db.get_connection() as conn:
            conn.execute(
                "UPDATE calendar_events SET start = ?, end = ? WHERE id = ?",
                (_stored(start), _stored(end), event_id),
            )
        return self._get(event_id)

    def delete_block(self, event_id):
        self._get_editable(event_id)
        self._delete(event_id)

    def clear(self):
        """Remove every event, fixed and TempoAI. Used when switching
        months."""
        with db.get_connection() as conn:
            conn.execute("DELETE FROM calendar_events")

    def _insert(self, event, editable, all_day):
        start = to_local(event["start"])
        end = to_local(event["end"])
        if end <= start:
            raise ValueError("Event end must be after its start.")

        event_id = str(uuid4())
        with db.get_connection() as conn:
            conn.execute("""
                INSERT INTO calendar_events (
                    id, title, start, end, editable, all_day, task_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                event_id, event["title"], _stored(start), _stored(end),
                int(editable), int(all_day), event.get("task_id"),
            ))
        return self._get(event_id)

    def _delete(self, event_id):
        with db.get_connection() as conn:
            conn.execute(
                "DELETE FROM calendar_events WHERE id = ?", (event_id,)
            )

    def _get(self, event_id):
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM calendar_events WHERE id = ?", (event_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Event not found: {event_id}")
        return self._row_to_event(row)

    def _get_editable(self, event_id):
        event = self._get(event_id)
        if not event["editable"]:
            raise PermissionError(
                "TempoAI can only modify events it created."
            )
        return event

    @staticmethod
    def _row_to_event(row):
        return {
            "id": row["id"],
            "title": row["title"],
            "start": to_local(row["start"]).astimezone(),
            "end": to_local(row["end"]).astimezone(),
            "editable": bool(row["editable"]),
            "all_day": bool(row["all_day"]),
            "task_id": row["task_id"],
        }
