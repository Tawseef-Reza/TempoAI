"""What time it is for TempoAI.

The calendars are fixed one-month schedules, so time is simulated and
only moves when the user sets it with /now.
"""

from datetime import datetime, time

from database import db
from scheduling.scheduler import to_local


def default_now():
    """Monday 08:00 of the loaded month (or of this week)."""
    from calendar_integration.templates import template_start

    template = db.get_setting("template")
    if template:
        start = datetime.fromisoformat(template["start"]).date()
    else:
        start = template_start()
    return to_local(datetime.combine(start, time(8, 0)))


def get_now():
    stored = db.get_setting("sim_now")
    return to_local(stored) if stored else default_now()


def set_now(value):
    now = to_local(value)
    db.set_setting("sim_now", now.isoformat())
    return now
