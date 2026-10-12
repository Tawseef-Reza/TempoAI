"""Usage limits for a publicly used (paid) Claude key: messages per person
per day and a daily dollar budget for the whole app. Configure in .env;
AI_LIMITS_ENABLED=false turns them off. Your Anthropic workspace spend
limit is the backstop.

Limits use the real clock, never the simulated calendar time.
"""

from datetime import date

import config
from database import db


class LimitReached(Exception):
    pass


def _today():
    return date.today().isoformat()


def cost_usd(usage):
    """Dollar cost of one response. Cached input is counted at the full
    input price, so this slightly overestimates."""
    return (
        usage.get("input_tokens", 0) * config.CLAUDE_INPUT_USD_PER_MTOK
        + usage.get("output_tokens", 0) * config.CLAUDE_OUTPUT_USD_PER_MTOK
    ) / 1_000_000


def check_message(user_key, message):
    """Raise LimitReached if this message shouldn't go to the AI."""
    if not config.AI_LIMITS_ENABLED:
        return
    if len(message) > config.AI_MAX_MESSAGE_CHARS:
        raise LimitReached(
            f"Please keep messages under {config.AI_MAX_MESSAGE_CHARS} "
            "characters."
        )
    if db.get_usage(_today(), user_key)["messages"] \
            >= config.AI_MESSAGES_PER_USER_PER_DAY:
        raise LimitReached(
            f"You've reached today's limit of "
            f"{config.AI_MESSAGES_PER_USER_PER_DAY} messages to TempoAI. "
            "Task commands still work; try again tomorrow."
        )
    if db.get_usage(_today())["cost_usd"] >= config.AI_DAILY_BUDGET_USD:
        raise LimitReached(
            "TempoAI's AI budget for today is used up. Task commands still "
            "work; try again tomorrow."
        )


def record_message(user_key):
    db.add_usage(_today(), user_key, messages=1)


def record_call(user_key, usage):
    db.add_usage(_today(), user_key, cost_usd=cost_usd(usage))
