"""Write an approved plan to the calendar: every upcoming TempoAI block is
replaced by the plan's blocks. Fixed events are never touched."""


def apply_plan(calendar, plan, now):
    """Returns (blocks removed, blocks added)."""
    if not plan.ok:
        raise ValueError("This plan breaks the rules and can't be applied.")

    upcoming = [
        event for event in calendar.get_events(now)
        if event["editable"] and event["start"] >= now
    ]
    for event in upcoming:
        calendar.delete_block(event["id"])
    for block in plan.blocks:
        calendar.create_block({
            "title": block.title,
            "start": block.start,
            "end": block.end,
            "task_id": block.task_id,
        })
    return len(upcoming), len(plan.blocks)
