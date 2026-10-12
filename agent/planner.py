"""TempoAI's planner: tasks + free time in, a complete plan out.

Python gathers the tasks and the free time, the AI returns every work
block as JSON, and Python checks the basic rules (sending the problems
back for a retry if needed). Every plan is complete: applying it replaces
all upcoming TempoAI blocks.
"""

import json
from dataclasses import dataclass, field
from datetime import timedelta

from agent import clock, limits, llm
from config import PLANNING_HORIZON_DAYS
from database import db
from scheduling.scheduler import (
    ProposedBlock,
    busy_from_events,
    fixed_events,
    free_slots,
    minutes_between,
    to_local,
)
from scheduling.validator import validate_plan

PROMPT = """\
You are TempoAI. Plan when the user works on their tasks.
Put the tasks into the free time as blocks (start/end, local ISO 8601).
- Only use free time; blocks must not overlap.
- Every block of a task ends before that task's deadline.
- Give each task its minutes_left, never more. Sessions of 30-90 minutes, \
spread out before the deadline.
- Follow the user's message and preferences.
- Plan every task. Only if there isn't enough time, leave out the least \
important work (priority 1 = most important)."""

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                },
                "required": ["task_id", "start", "end"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["blocks"],
    "additionalProperties": False,
}

# Retries after a plan breaks a rule (so at most 3 model calls).
MAX_RETRIES = 2

APPLY_HINT = ("Rules from your messages aren't kept after applying; put "
              "lasting ones in your preferences (/prefs).")


def didnt_fit_lines(plan, now):
    """One line per task the plan left work out of."""
    lines = []
    for task_id, minutes in plan.didnt_fit.items():
        task = db.get_task(task_id)
        passed = task["deadline"] and to_local(task["deadline"]) <= now
        lines.append(f"{minutes} min of '{task['title']}' didn't fit"
                     + (" (deadline passed)" if passed else ""))
    return lines


@dataclass
class Plan:
    blocks: list = field(default_factory=list)      # ProposedBlock
    didnt_fit: dict = field(default_factory=dict)   # task_id -> minutes
    errors: list = field(default_factory=list)      # rules still broken
    history: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.errors


def _days(slots, events):
    """Free time and named fixed events per day, in date order."""
    by_day = {}

    def day_for(moment):
        return by_day.setdefault(moment.date(), {
            "date": moment.strftime("%a %Y-%m-%d"),
            "free": [],
            "busy": [],
        })

    for slot in slots:
        day_for(slot.start)["free"].append(
            f"{slot.start:%H:%M}-{slot.end:%H:%M}")
    for event in fixed_events(events):
        day_for(event["start"])["busy"].append(
            f"{event['start']:%H:%M}-{event['end']:%H:%M} {event['title']}")
    return [by_day[d] for d in sorted(by_day)]


def build_context(calendar, now):
    """What the AI sees, plus the events and availability to check
    against."""
    end = now + timedelta(days=PLANNING_HORIZON_DAYS)
    events = calendar.get_events(now, end)
    windows = calendar.get_availability(now, end)
    slots = free_slots(windows, busy_from_events(events), now)

    context = {
        "now": now.isoformat(timespec="minutes"),
        "tasks": [
            {"id": t["id"], "title": t["title"],
             "minutes_left": t["remaining_minutes"],
             "deadline": t["deadline"],
             "priority": t["priority"]}
            for t in db.get_tasks()
        ],
        "days": _days(slots, events),
    }
    preferences = db.get_preferences()
    if preferences:
        context["preferences"] = preferences
    return context, events, windows


def _parse_blocks(reply, titles):
    """ProposedBlocks from the AI's JSON, plus errors for unreadable
    ones."""
    blocks, errors = [], []
    for item in reply.get("blocks", []):
        try:
            task_id = int(item["task_id"])
            blocks.append(ProposedBlock(
                task_id, titles.get(task_id, f"Task {task_id}"),
                to_local(item["start"]), to_local(item["end"]),
            ))
        except (KeyError, TypeError, ValueError):
            errors.append(f"Unreadable block {json.dumps(item)}")
    return blocks, errors


def make_plan(message, calendar, history=None, now=None, user_key="local"):
    """Ask the AI for a complete plan. Pass the returned history back in
    for a follow-up before the plan is applied.

    Raises limits.LimitReached (before any model request) if the user is
    over a usage limit."""
    limits.check_message(user_key, message)
    provider = llm.get_provider()
    limits.record_message(user_key)
    db.log_trace("user_message", arguments=message)

    now = to_local(now) if now is not None else clock.get_now()
    context, events, windows = build_context(calendar, now)
    system = [PROMPT, "Context: " + json.dumps(context,
                                               separators=(",", ":"))]
    tasks = db.get_tasks()
    titles = {t["id"]: t["title"] for t in tasks}

    history = list(history or [])
    provider.add_user_message(history, message)

    for _ in range(1 + MAX_RETRIES):
        reply, usage = provider.respond(history, system, PLAN_SCHEMA)
        limits.record_call(user_key, usage)
        db.log_trace("model_call", arguments=reply, result=usage)

        blocks, errors = _parse_blocks(reply, titles)
        errors += [v["details"] for v in
                   validate_plan(blocks, tasks, events, windows, now)]
        db.log_trace("check", result=errors)
        if not errors:
            break
        provider.add_user_message(
            history,
            "Your plan breaks these rules. Fix them and send the whole "
            "plan again:\n- " + "\n- ".join(errors),
        )

    scheduled = {}
    for block in blocks:
        scheduled[block.task_id] = scheduled.get(block.task_id, 0) + \
            minutes_between(block.start, block.end)
    didnt_fit = {
        t["id"]: t["remaining_minutes"] - scheduled.get(t["id"], 0)
        for t in tasks if scheduled.get(t["id"], 0) < t["remaining_minutes"]
    }
    return Plan(
        blocks=sorted(blocks, key=lambda b: b.start),
        didnt_fit=didnt_fit,
        errors=errors,
        history=history,
    )
