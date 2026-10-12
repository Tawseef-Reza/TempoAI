"""The Streamlit app, run headless with Streamlit's AppTest and the fake
model (no network)."""

from datetime import date, datetime, time, timedelta

from streamlit.testing.v1 import AppTest

from agent import limits
from config import get_calendar
from database import db
from scheduling.scheduler import to_local
from tests.conftest import reply


def start_app():
    app = AppTest.from_file("../app.py", default_timeout=30)
    app.run()
    assert not app.exception
    return app


def button(app, label):
    return next(b for b in app.button if b.label == label)


def load_worker_month(app):
    app.selectbox(key="month").set_value("worker_9_5")
    app.button(key="load").click()
    app.run()
    assert not app.exception


def use_db_of(app):
    db.use_session_db(db.sessions_dir() / f"{app.session_state['sid']}.db")


def add_task(app, title, minutes):
    app.text_input(key="new_title").set_value(title)
    app.number_input(key="new_minutes").set_value(minutes)
    button(app, "Add task").click()
    app.run()
    assert not app.exception


def tuesday_evening():
    template_start = date.fromisoformat(db.get_setting("template")["start"])
    tuesday = template_start + timedelta(days=1)
    return (to_local(datetime.combine(tuesday, time(19, 0))),
            to_local(datetime.combine(tuesday, time(20, 0))))


def test_app_asks_for_a_month_first():
    app = start_app()

    assert "Load month" in app.info[0].value


def test_load_month_add_task_plan_and_apply(scripted_llm):
    app = start_app()
    load_worker_month(app)
    add_task(app, "Essay", 60)
    use_db_of(app)
    assert [t["title"] for t in db.get_tasks()] == ["Essay"]

    start, end = tuesday_evening()
    scripted_llm.script.append(reply((1, start, end)))
    app.chat_input[0].set_value("plan my week").run()
    assert not app.exception
    assert app.session_state["plan"].ok
    assert any("Here's a plan" in s.value for s in app.success)

    app.button(key="apply").click().run()
    assert not app.exception
    applied = [e for e in get_calendar().get_events() if e["editable"]]
    assert [(e["title"], e["start"]) for e in applied] == [("Essay", start)]
    assert app.session_state["plan"] is None
    assert any("aren't kept after applying" in s.value for s in app.success)


def test_each_visitor_has_their_own_data_but_shared_usage(scripted_llm):
    first, second = start_app(), start_app()
    load_worker_month(first)
    load_worker_month(second)
    add_task(first, "Only in the first session", 60)

    use_db_of(second)
    assert db.get_tasks() == []

    scripted_llm.script += [reply(), reply()]
    first.chat_input[0].set_value("plan").run()
    second.chat_input[0].set_value("plan").run()
    assert db.get_usage(limits._today())["messages"] == 2
