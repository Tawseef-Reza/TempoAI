import pytest

import config
from agent import limits, planner
from calendar_integration.local_calendar import LocalCalendar
from database import db
from tests.conftest import reply


@pytest.fixture
def limited(monkeypatch):
    monkeypatch.setattr(config, "AI_LIMITS_ENABLED", True)
    monkeypatch.setattr(config, "AI_MESSAGES_PER_USER_PER_DAY", 3)
    monkeypatch.setattr(config, "AI_MAX_MESSAGE_CHARS", 50)
    monkeypatch.setattr(config, "AI_DAILY_BUDGET_USD", 1.00)


def send(scripted_llm, message="plan my week", user="alice"):
    scripted_llm.script.append(reply())
    return planner.make_plan(message, LocalCalendar(), user_key=user)


def test_per_user_daily_cap(limited, scripted_llm):
    for _ in range(3):
        send(scripted_llm)

    with pytest.raises(limits.LimitReached, match="today's limit"):
        send(scripted_llm)
    # Another user is unaffected.
    send(scripted_llm, user="bob")
    assert len(scripted_llm.requests) == 4  # no request for the blocked one


def test_message_length_cap(limited, scripted_llm):
    with pytest.raises(limits.LimitReached, match="under 50"):
        send(scripted_llm, message="x" * 51)
    assert scripted_llm.requests == []


def test_daily_dollar_budget_for_the_whole_app(limited, scripted_llm,
                                               monkeypatch):
    # Each fake call reports 100 input + 10 output tokens.
    per_call = limits.cost_usd({"input_tokens": 100, "output_tokens": 10})
    monkeypatch.setattr(config, "AI_DAILY_BUDGET_USD", per_call * 2)
    send(scripted_llm, user="a")
    send(scripted_llm, user="b")

    with pytest.raises(limits.LimitReached, match="budget for today"):
        send(scripted_llm, user="c")


def test_cost_uses_haiku_prices():
    # 1M input + 1M output tokens = $0.10 + $0.50.
    assert limits.cost_usd({"input_tokens": 1_000_000,
                            "output_tokens": 1_000_000}) == pytest.approx(0.60)


def test_usage_is_recorded(limited, scripted_llm):
    send(scripted_llm)

    mine = db.get_usage(limits._today(), "alice")
    assert mine["messages"] == 1
    assert mine["cost_usd"] == pytest.approx(
        limits.cost_usd({"input_tokens": 100, "output_tokens": 10}))


def test_new_day_resets_counts(limited, scripted_llm, monkeypatch):
    for _ in range(3):
        send(scripted_llm)
    monkeypatch.setattr(limits, "_today", lambda: "2099-01-01")

    send(scripted_llm)  # allowed again


def test_limits_off_bypasses_everything(scripted_llm):
    # conftest turns limits off by default
    for _ in range(5):
        send(scripted_llm, message="x" * 5000)
    assert db.get_usage(limits._today(), "alice")["messages"] == 5
