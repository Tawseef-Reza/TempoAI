from datetime import date, datetime, timedelta

import pytest

from calendar_integration.local_calendar import LocalCalendar
from calendar_integration.templates import (
    TEMPLATES,
    check_in_month,
    load_template,
    loaded_template,
)
from database import db
from scheduling.scheduler import to_local

MONDAY = date(2026, 10, 12)


def at(day, hour, minute=0):
    return to_local(datetime(2026, 10, day, hour, minute))


def test_create_read_move_delete_persists():
    calendar = LocalCalendar()
    block = calendar.create_block({
        "title": "Study", "start": at(12, 14), "end": at(12, 15),
        "task_id": 3,
    })

    # A fresh instance reads the same SQLite data.
    events = LocalCalendar().get_events()
    assert len(events) == 1
    assert events[0]["task_id"] == 3
    assert events[0]["editable"] is True

    moved = calendar.move_block(block["id"], at(12, 16), at(12, 17))
    assert moved["start"] == at(12, 16)

    calendar.delete_block(block["id"])
    assert calendar.get_events() == []


def test_fixed_events_cannot_be_changed_by_tempoai():
    calendar = LocalCalendar()
    fixed = calendar.add_fixed_event("Class", at(12, 9), at(12, 10))

    with pytest.raises(PermissionError):
        calendar.move_block(fixed["id"], at(12, 11), at(12, 12))
    with pytest.raises(PermissionError):
        calendar.delete_block(fixed["id"])


def test_get_events_filters_by_time_range():
    calendar = LocalCalendar()
    calendar.add_fixed_event("Monday", at(12, 9), at(12, 10))
    calendar.add_fixed_event("Tuesday", at(13, 9), at(13, 10))

    events = calendar.get_events(at(13, 0), at(14, 0))

    assert [e["title"] for e in events] == ["Tuesday"]


@pytest.mark.parametrize("name", sorted(set(TEMPLATES) - {"custom"}))
def test_templates_load_a_month_of_fixed_events(name):
    calendar = LocalCalendar()

    count = load_template(calendar, name, today=MONDAY + timedelta(days=2))
    events = calendar.get_events()

    assert count == len(events) > 0
    assert all(not e["editable"] for e in events)
    assert events[0]["start"].date() >= MONDAY
    assert events[-1]["end"].date() < MONDAY + timedelta(days=28)
    assert db.get_setting("template")["name"] == name
    assert calendar.availability_pattern == TEMPLATES[name]["availability"]


def test_loading_a_template_replaces_previous_events():
    calendar = LocalCalendar()
    calendar.create_block({
        "title": "Old block", "start": at(12, 14), "end": at(12, 15)
    })

    load_template(calendar, "vacation", today=MONDAY)

    assert all(e["title"] != "Old block" for e in calendar.get_events())


def test_unknown_template_raises():
    with pytest.raises(ValueError):
        load_template(LocalCalendar(), "astronaut")


def test_custom_template_starts_empty():
    calendar = LocalCalendar()

    assert load_template(calendar, "custom", today=MONDAY) == 0
    assert calendar.get_events() == []
    assert loaded_template() == "custom"


def test_fixed_events_can_be_removed_but_blocks_cannot_that_way():
    calendar = LocalCalendar()
    fixed = calendar.add_fixed_event("Gym", at(12, 18), at(12, 19))
    block = calendar.create_block({
        "title": "Study", "start": at(12, 14), "end": at(12, 15),
    })

    with pytest.raises(PermissionError):
        calendar.remove_fixed_event(block["id"])
    calendar.remove_fixed_event(fixed["id"])

    assert [e["id"] for e in calendar.get_events()] == [block["id"]]


def test_events_must_be_inside_the_loaded_month():
    load_template(LocalCalendar(), "custom", today=MONDAY)

    last_day = to_local(datetime(2026, 11, 8, 22))  # day 28 of the month
    day_after = to_local(datetime(2026, 11, 9, 9))

    check_in_month(at(12, 9), at(12, 10))
    check_in_month(last_day, last_day + timedelta(hours=1))
    with pytest.raises(ValueError, match="within the month"):
        check_in_month(at(11, 9), at(11, 10))
    with pytest.raises(ValueError, match="within the month"):
        check_in_month(day_after, day_after + timedelta(hours=1))
