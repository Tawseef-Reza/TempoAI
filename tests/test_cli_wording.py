from datetime import datetime

from agent.cli import Session
from agent.planner import APPLY_HINT, Plan, didnt_fit_lines
from database import db
from scheduling.scheduler import to_local

NOW = to_local(datetime(2026, 10, 12, 8, 0))


def test_overdue_tasks_say_deadline_passed():
    late = db.create_task("Lab prelab", 45, deadline="2026-10-07T14:00:00")
    open_ = db.create_task("Essay", 60, deadline="2026-10-16T23:59:00")
    plan = Plan(didnt_fit={late["id"]: 45, open_["id"]: 30})

    assert didnt_fit_lines(plan, NOW) == [
        "45 min of 'Lab prelab' didn't fit (deadline passed)",
        "30 min of 'Essay' didn't fit",
    ]


def test_apply_prints_the_prefs_hint(capsys):
    session = Session()
    session.plan = Plan()

    session.cmd_apply([])

    assert APPLY_HINT in capsys.readouterr().out
