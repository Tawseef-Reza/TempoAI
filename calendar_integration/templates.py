"""One-month template calendars for the local calendar.

Each template has a weekly availability pattern (when the person is
willing to work on tasks) and the fixed events of a typical month. Events
start on Monday of the current week, so the demo always shows "now".
"custom" starts empty; the user adds and removes its fixed events.
"""

from datetime import date, datetime, time, timedelta

from calendar_integration.local_calendar import DEFAULT_AVAILABILITY
from database import db
from scheduling.scheduler import to_local

TEMPLATE_DAYS = 28

MON, TUE, WED, THU, FRI, SAT, SUN = range(7)
WEEKDAYS = (MON, TUE, WED, THU, FRI)


def _weekly(start, days, weekdays, open_at, close_at, title):
    """Repeat an event on the given weekdays across the whole template."""
    events = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        if day.weekday() in weekdays:
            events.append(_once(day, open_at, close_at, title))
    return events


def _once(day, open_at, close_at, title):
    return (
        title,
        datetime.combine(day, time.fromisoformat(open_at)),
        datetime.combine(day, time.fromisoformat(close_at)),
    )


def _worker_events(start, days):
    events = (
        _weekly(start, days, WEEKDAYS, "08:15", "09:00", "Commute")
        + _weekly(start, days, WEEKDAYS, "09:00", "17:00", "Work")
        + _weekly(start, days, WEEKDAYS, "17:00", "17:45", "Commute")
        + _weekly(start, days, (MON, WED, FRI), "18:30", "19:30", "Gym")
        + _weekly(start, days, (SAT,), "10:00", "12:00", "Soccer league")
        + _weekly(start, days, (SUN,), "11:00", "12:00", "Groceries")
    )
    events += [
        _once(start + timedelta(days=10), "19:00", "21:00", "Team dinner"),
        _once(start + timedelta(days=15), "18:00", "19:00", "Dentist"),
        _once(start + timedelta(days=19), "13:00", "18:00", "Friend's wedding"),
    ]
    return events


def _student_events(start, days):
    events = (
        _weekly(start, days, (MON, WED, FRI), "09:00", "09:50", "Calculus I")
        + _weekly(start, days, (MON, WED, FRI), "11:00", "11:50",
                  "Intro to Psychology")
        + _weekly(start, days, (TUE, THU), "10:00", "11:15",
                  "English Composition")
        + _weekly(start, days, (TUE, THU), "13:00", "14:15", "Chemistry")
        + _weekly(start, days, (WED,), "14:00", "16:50", "Chemistry lab")
        + _weekly(start, days, (TUE, THU), "17:00", "21:00",
                  "Campus job shift")
        + _weekly(start, days, (SAT,), "10:00", "14:00", "Campus job shift")
        + _weekly(start, days, (MON,), "18:00", "19:00", "Robotics club")
    )
    events += [
        _once(start + timedelta(days=17), "15:00", "16:00",
              "Office hours: Chemistry"),
        _once(start + timedelta(days=24), "13:00", "14:15",
              "Chemistry midterm"),
    ]
    return events


def _vacation_events(start, days):
    return [
        _once(start, "08:00", "14:00", "Flight to Lisbon"),
        _once(start + timedelta(days=1), "10:00", "13:00",
              "Walking tour: Alfama"),
        _once(start + timedelta(days=2), "19:30", "21:30",
              "Dinner reservation"),
        _once(start + timedelta(days=4), "09:00", "18:00", "Day trip: Sintra"),
        _once(start + timedelta(days=8), "11:00", "14:00", "Train to Porto"),
        _once(start + timedelta(days=9), "15:00", "17:00", "Port wine tasting"),
        _once(start + timedelta(days=12), "09:00", "17:00",
              "Douro valley tour"),
        _once(start + timedelta(days=15), "10:00", "13:00", "Train to Madrid"),
        _once(start + timedelta(days=16), "10:00", "13:00", "Prado museum"),
        _once(start + timedelta(days=19), "20:00", "23:00", "Flamenco show"),
        _once(start + timedelta(days=22), "09:00", "16:00", "Toledo day trip"),
        _once(start + timedelta(days=days - 1), "12:00", "20:00",
              "Flight home"),
    ]


TEMPLATES = {
    "worker_9_5": {
        "label": "9-5 worker",
        "availability": {
            **{day: [("06:30", "08:15"), ("17:45", "23:00")]
               for day in WEEKDAYS},
            SAT: [("08:00", "23:00")],
            SUN: [("08:00", "22:00")],
        },
        "events": _worker_events,
    },
    "college_student": {
        "label": "College student",
        "availability": {day: [("08:00", "23:30")] for day in range(7)},
        "events": _student_events,
    },
    "vacation": {
        "label": "On vacation",
        "availability": {day: [("08:00", "12:00"), ("14:00", "19:00")]
                         for day in range(7)},
        "events": _vacation_events,
    },
    "custom": {
        "label": "Custom",
        "availability": DEFAULT_AVAILABILITY,
        "events": lambda start, days: [],
    },
}


def template_start(today=None):
    today = today or date.today()
    return today - timedelta(days=today.weekday())


def load_template(calendar, name, today=None):
    """Replace the local calendar's events with a template's month.

    Tasks are kept; existing TempoAI blocks are removed with the old
    calendar, so the next plan starts fresh.
    """
    if name not in TEMPLATES:
        raise ValueError(
            f"Unknown template '{name}'. Choose from {sorted(TEMPLATES)}"
        )
    template = TEMPLATES[name]
    start = template_start(today)

    calendar.clear()
    calendar.set_availability_pattern(template["availability"])
    events = template["events"](start, TEMPLATE_DAYS)
    for title, event_start, event_end in events:
        calendar.add_fixed_event(title, event_start, event_end)

    db.set_setting("template", {
        "name": name,
        "start": start.isoformat(),
        "end": (start + timedelta(days=TEMPLATE_DAYS)).isoformat(),
    })
    # Simulated time restarts at the beginning of the persona's month.
    db.set_setting(
        "sim_now", datetime.combine(start, time(8, 0)).astimezone().isoformat()
    )
    return len(events)


def loaded_template():
    """Name of the loaded month, or None."""
    template = db.get_setting("template")
    return template["name"] if template else None


def check_in_month(start, end):
    """Raise ValueError unless start..end lies inside the loaded month."""
    template = db.get_setting("template")
    if template is None:
        raise ValueError("Load a month first, e.g. /persona custom")
    month_start = to_local(datetime.fromisoformat(template["start"]))
    month_end = to_local(datetime.fromisoformat(template["end"]))
    if not (month_start <= to_local(start) and to_local(end) <= month_end):
        raise ValueError(
            f"Events must be within the month "
            f"{month_start:%b %d} - {month_end - timedelta(days=1):%b %d}."
        )
