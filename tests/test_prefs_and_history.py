from datetime import datetime

import pytest

from agent import task_actions
from agent.cli import Session
from agent.planner import Plan, build_context
from calendar_integration.local_calendar import LocalCalendar
from calendar_integration.templates import load_template
from database import db
from scheduling.scheduler import ProposedBlock, to_local

NOW = to_local(datetime(2026, 10, 12, 8, 0))


def calendar():
    cal = LocalCalendar()
    cal.set_availability_pattern({d: [("09:00", "17:00")] for d in range(7)})
    return cal


def test_preferences_reach_the_ai():
    task_actions.set_preferences("no work before 10am, don't cram")

    context, _, _ = build_context(calendar(), NOW)

    assert context["preferences"] == "no work before 10am, don't cram"


def test_clearing_preferences():
    task_actions.set_preferences("evenings only")
    task_actions.set_preferences("")

    context, _, _ = build_context(calendar(), NOW)

    assert "preferences" not in context


def test_apply_starts_a_fresh_conversation():
    session = Session()
    session.calendar = calendar()
    task = db.create_task("Essay", 60)
    session.plan = Plan(blocks=[ProposedBlock(
        task["id"], "Essay", to_local(datetime(2026, 10, 12, 9)),
        to_local(datetime(2026, 10, 12, 10)),
    )])
    session.history = ["earlier messages"]

    session.cmd_apply([])

    assert session.history is None
    assert session.plan is None
    assert len([e for e in session.calendar.get_events()
                if e["editable"]]) == 1


def test_discard_starts_a_fresh_conversation():
    session = Session()
    session.history = ["earlier messages"]
    session.plan = Plan()

    session.cmd_discard([])

    assert session.history is None
    assert session.plan is None


# ---------- /event on the custom month ----------

@pytest.fixture
def custom_session():
    session = Session()
    load_template(session.calendar, "custom",
                  today=datetime(2026, 10, 12).date())
    return session


def test_event_add_and_remove(custom_session):
    custom_session.cmd_event(["add", "Gym", "2026-10-13", "18:00",
                              "2026-10-13", "19:00"])
    event = custom_session.calendar.get_events()[0]
    assert (event["title"], event["editable"]) == ("Gym", False)
    assert custom_session.fixed_labels() == {event["id"]: "e1"}

    custom_session.cmd_event(["remove", "e1"])

    assert custom_session.calendar.get_events() == []


def test_event_add_rejects_times_outside_the_month(custom_session):
    with pytest.raises(ValueError, match="within the month"):
        custom_session.cmd_event(["add", "Trip", "2026-12-01T09:00",
                                  "2026-12-01T10:00"])


def test_event_commands_only_work_on_the_custom_month():
    session = Session()
    load_template(session.calendar, "worker_9_5",
                  today=datetime(2026, 10, 12).date())

    with pytest.raises(ValueError, match="custom month"):
        session.cmd_event(["add", "Gym", "2026-10-13T18:00",
                           "2026-10-13T19:00"])
