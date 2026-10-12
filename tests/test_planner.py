from datetime import datetime

import pytest

from agent import planner
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


def test_valid_plan_in_one_call(scripted_llm, calendar):
    essay = db.create_task("Essay", 120, deadline="2026-10-16T23:59:00")
    scripted_llm.script.append(reply(
        (essay["id"], at(13, 9), at(13, 10)),
        (essay["id"], at(12, 11, 10), at(12, 12, 10)),
    ))

    plan = planner.make_plan("Plan my week", calendar, now=NOW)

    assert plan.ok and len(scripted_llm.requests) == 1
    assert [b.start for b in plan.blocks] == [at(12, 11, 10), at(13, 9)]
    assert plan.didnt_fit == {}
    # Nothing is written to the calendar before /apply.
    assert all(not e["editable"] for e in calendar.get_events())


def test_broken_rules_are_sent_back_for_a_retry(scripted_llm, calendar):
    essay = db.create_task("Essay", 60)
    scripted_llm.script += [
        reply((essay["id"], at(12, 10), at(12, 11))),  # during the class
        reply((essay["id"], at(12, 12), at(12, 13))),
    ]

    plan = planner.make_plan("Plan", calendar, now=NOW)

    assert plan.ok and len(scripted_llm.requests) == 2
    feedback = scripted_llm.requests[1]["contents"][-1]["text"]
    assert "overlaps a fixed event" in feedback


def test_gives_up_after_the_retries(scripted_llm, calendar):
    essay = db.create_task("Essay", 60)
    bad = reply((essay["id"], at(12, 10), at(12, 11)))
    scripted_llm.script += [bad] * (1 + planner.MAX_RETRIES)

    plan = planner.make_plan("Plan", calendar, now=NOW)

    assert not plan.ok
    assert len(scripted_llm.requests) == 1 + planner.MAX_RETRIES


def test_work_left_out_is_reported_as_didnt_fit(scripted_llm, calendar):
    essay = db.create_task("Essay", 60, priority=1)
    garage = db.create_task("Garage", 90, priority=5)
    scripted_llm.script.append(reply(
        (essay["id"], at(12, 12), at(12, 13)),
        (garage["id"], at(12, 14), at(12, 14, 30)),
    ))

    plan = planner.make_plan("Plan", calendar, now=NOW)

    assert plan.ok
    assert plan.didnt_fit == {garage["id"]: 60}


def test_context_has_tasks_free_time_and_event_names(scripted_llm, calendar):
    db.create_task("Essay", 60, deadline="2026-10-16T23:59:00", priority=2)
    db.set_preferences("no work after 4pm")
    scripted_llm.script.append(reply())

    planner.make_plan("Plan", calendar, now=NOW)

    instructions, context = scripted_llm.requests[0]["system"]
    assert instructions == planner.PROMPT
    assert '"title":"Essay","minutes_left":60' in context
    assert '"free":["11:00-17:00"],"busy":["09:00-11:00 Class"]' in context
    assert '"preferences":"no work after 4pm"' in context
    assert scripted_llm.requests[0]["schema"] == planner.PLAN_SCHEMA


def test_unreadable_blocks_are_errors(scripted_llm, calendar):
    db.create_task("Essay", 60)
    scripted_llm.script += [
        {"blocks": [{"task_id": 1, "start": "soon", "end": "later"}]}
    ] * (1 + planner.MAX_RETRIES)

    plan = planner.make_plan("Plan", calendar, now=NOW)

    assert not plan.ok and "Unreadable block" in plan.errors[0]


def test_every_step_is_logged(scripted_llm, calendar):
    essay = db.create_task("Essay", 60)
    scripted_llm.script.append(reply((essay["id"], at(12, 12), at(12, 13))))

    planner.make_plan("Plan", calendar, now=NOW)

    assert [row["action"] for row in db.get_trace()] == [
        "user_message", "model_call", "check"]


def test_follow_ups_keep_the_conversation(scripted_llm, calendar):
    scripted_llm.script += [reply(), reply()]

    first = planner.make_plan("one", calendar, now=NOW)
    planner.make_plan("two", calendar, history=first.history, now=NOW)

    assert len(scripted_llm.requests[1]["contents"]) == 3
