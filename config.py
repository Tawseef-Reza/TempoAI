"""App-wide settings read from .env."""

import os

from dotenv import load_dotenv

load_dotenv()

# How far ahead the agent plans.
PLANNING_HORIZON_DAYS = int(os.getenv("PLANNING_HORIZON_DAYS", "14"))

# Usage limits for a publicly used Claude key: per person per day, and a
# daily dollar budget for the whole app.
AI_LIMITS_ENABLED = os.getenv("AI_LIMITS_ENABLED", "true").lower() == "true"
AI_MESSAGES_PER_USER_PER_DAY = int(
    os.getenv("AI_MESSAGES_PER_USER_PER_DAY", "40"))
AI_MAX_MESSAGE_CHARS = int(os.getenv("AI_MAX_MESSAGE_CHARS", "1000"))
AI_DAILY_BUDGET_USD = float(os.getenv("AI_DAILY_BUDGET_USD", "1.50"))

# Claude Haiku 5.5 prices per million tokens (prompts under 100K tokens).
CLAUDE_INPUT_USD_PER_MTOK = float(os.getenv("CLAUDE_INPUT_USD_PER_MTOK",
                                            "0.10"))
CLAUDE_OUTPUT_USD_PER_MTOK = float(os.getenv("CLAUDE_OUTPUT_USD_PER_MTOK",
                                             "0.50"))


def get_calendar():
    from calendar_integration.local_calendar import LocalCalendar
    return LocalCalendar()
