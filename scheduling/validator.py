"""The basic rules every plan must follow. Returns structured violations;
the AI cannot override these rules. Work left out of a plan is not a
violation: it's shown to the user as "didn't fit"."""

from scheduling.scheduler import (
    busy_from_events,
    get_field,
    minutes_between,
    to_local,
)


def _violation(kind, details, task_id=None):
    return {"type": kind, "task_id": task_id, "details": details}


def validate_plan(blocks, tasks, events, availability, now):
    """Check proposed blocks against tasks, fixed events and availability.

    blocks may be ProposedBlock objects or dicts with task_id/start/end.
    """
    now = to_local(now)
    tasks_by_id = {get_field(task, "id"): task for task in tasks}
    fixed = busy_from_events(events)
    windows = [(to_local(w.start), to_local(w.end)) for w in availability]
    violations = []
    valid = []  # (task_id, start, end) for blocks with sane times

    for block in blocks:
        task_id = get_field(block, "task_id")
        start = to_local(get_field(block, "start"))
        end = to_local(get_field(block, "end"))
        label = f"{start:%a %Y-%m-%d %H:%M}-{end:%H:%M}"

        if end <= start:
            violations.append(_violation(
                "INVALID_DURATION", f"Block {label} ends before it starts",
                task_id,
            ))
            continue
        valid.append((task_id, start, end))

        task = tasks_by_id.get(task_id)
        if task is None:
            violations.append(_violation(
                "UNKNOWN_TASK", f"No open task with id {task_id}", task_id
            ))
            continue

        if start < now:
            violations.append(_violation(
                "IN_PAST", f"Block {label} starts in the past", task_id
            ))

        if not any(w_start <= start and end <= w_end
                   for w_start, w_end in windows):
            violations.append(_violation(
                "OUTSIDE_FREE_TIME",
                f"Block {label} is not inside free time", task_id,
            ))

        for interval in fixed:
            if start < interval.end and interval.start < end:
                violations.append(_violation(
                    "OVERLAP_FIXED",
                    f"Block {label} overlaps a fixed event "
                    f"{interval.start:%H:%M}-{interval.end:%H:%M}",
                    task_id,
                ))
                break

        deadline = to_local(get_field(task, "deadline"))
        if deadline is not None and end > deadline:
            violations.append(_violation(
                "MISSED_DEADLINE",
                f"Block {label} ends after the deadline "
                f"{deadline:%a %Y-%m-%d %H:%M}",
                task_id,
            ))

    # Blocks must not overlap each other.
    valid.sort(key=lambda item: item[1])
    for i, (task_id, start, end) in enumerate(valid):
        for _, other_start, _ in valid[i + 1:]:
            if other_start >= end:
                break
            violations.append(_violation(
                "OVERLAP_BLOCK", f"Blocks overlap at {other_start:%a %H:%M}",
                task_id,
            ))

    # A task never gets more minutes than it needs.
    scheduled = {}
    for task_id, start, end in valid:
        scheduled[task_id] = scheduled.get(task_id, 0) + \
            minutes_between(start, end)
    for task_id, task in tasks_by_id.items():
        remaining = get_field(task, "remaining_minutes") or 0
        if scheduled.get(task_id, 0) > remaining:
            violations.append(_violation(
                "TOO_MANY_MINUTES",
                f"Task '{get_field(task, 'title')}' has "
                f"{scheduled[task_id]} minutes planned but needs only "
                f"{remaining}",
                task_id,
            ))

    return violations
