from datetime import datetime

import pytest

from agent import planner
from agent.apply import apply_plan
from calendar_integration.local_calendar import LocalCalendar
from database import db
from scheduling.scheduler import to_local
from tests.conftest import reply

NOW = to_local(datetime(2026, 10, 12, 8, 0))


def at(day, hour, minute=0):
    return to_local(datetime(2026, 10, day, hour, minute))


@pytest.fixture
def calendar():
    cal = LocalCalendar()
    cal.set_availability_pattern({d: [("09:00", "17:00")] for d in range(7)})
    cal.add_fixed_event("Class", at(12, 9), at(12, 11))
    return cal


def tempo_blocks(calendar):
    return [(e["task_id"], e["start"]) for e in calendar.get_events()
            if e["editable"]]


def test_apply_writes_the_plan(scripted_llm, calendar):
    essay = db.create_task("Essay", 120)
    scripted_llm.script.append(reply(
        (essay["id"], at(12, 11), at(12, 12)),
        (essay["id"], at(13, 9), at(13, 10)),
    ))
    plan = planner.make_plan("Plan it", calendar, now=NOW)

    assert apply_plan(calendar, plan, NOW) == (0, 2)
    assert tempo_blocks(calendar) == [(essay["id"], at(12, 11)),
                                      (essay["id"], at(13, 9))]
    assert any(e["title"] == "Class" for e in calendar.get_events())


def test_a_new_plan_replaces_upcoming_blocks_only(scripted_llm, calendar):
    essay = db.create_task("Essay", 60)
    # A block that already happened stays on the calendar.
    calendar.create_block({"title": "Essay", "task_id": essay["id"],
                           "start": at(11, 9), "end": at(11, 10)})
    scripted_llm.script += [
        reply((essay["id"], at(12, 11), at(12, 12))),
        reply((essay["id"], at(13, 14), at(13, 15))),
    ]
    apply_plan(calendar, planner.make_plan("Plan", calendar, now=NOW), NOW)

    second = planner.make_plan("Afternoon please", calendar, now=NOW)
    assert apply_plan(calendar, second, NOW) == (1, 1)

    assert tempo_blocks(calendar) == [(essay["id"], at(11, 9)),
                                      (essay["id"], at(13, 14))]


def test_apply_never_changes_tasks(scripted_llm, calendar):
    garage = db.create_task("Garage", 90)
    scripted_llm.script.append(reply((garage["id"], at(12, 12),
                                      at(12, 12, 30))))
    plan = planner.make_plan("Plan", calendar, now=NOW)

    apply_plan(calendar, plan, NOW)

    assert db.get_task(garage["id"])["remaining_minutes"] == 90


def test_broken_plans_cannot_be_applied(scripted_llm, calendar):
    essay = db.create_task("Essay", 60)
    scripted_llm.script += [reply((essay["id"], at(12, 10), at(12, 11)))] \
        * (1 + planner.MAX_RETRIES)
    plan = planner.make_plan("Plan", calendar, now=NOW)

    with pytest.raises(ValueError):
        apply_plan(calendar, plan, NOW)
