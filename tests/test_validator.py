from datetime import datetime

import pytest

from scheduling.scheduler import ProposedBlock, Window, to_local
from scheduling.validator import validate_plan

NOW = to_local(datetime(2026, 10, 12, 8, 0))
WINDOWS = [Window(
    to_local(datetime(2026, 10, 12, 9)), to_local(datetime(2026, 10, 12, 17))
)]


def at(day, hour, minute=0):
    return to_local(datetime(2026, 10, day, hour, minute))


def task(task_id, minutes, deadline=None):
    return {
        "id": task_id,
        "title": f"Task {task_id}",
        "priority": 3,
        "deadline": deadline.isoformat() if deadline else None,
        "remaining_minutes": minutes,
    }


def block(task_id, start, end):
    return ProposedBlock(task_id, f"Task {task_id}", start, end)


def types(violations):
    return sorted({v["type"] for v in violations})


def test_valid_plan_has_no_violations():
    blocks = [block(1, at(12, 9), at(12, 10))]

    assert validate_plan(blocks, [task(1, 60)], [], WINDOWS, NOW) == []


def test_leaving_work_out_is_not_a_violation():
    blocks = [block(1, at(12, 9), at(12, 10))]  # 60 of 120

    assert validate_plan(blocks, [task(1, 120)], [], WINDOWS, NOW) == []


@pytest.mark.parametrize("blocks, tasks, expected", [
    (
        [block(1, at(12, 10), at(12, 9))],
        [task(1, 60)],
        "INVALID_DURATION",
    ),
    (
        [block(99, at(12, 9), at(12, 10))],
        [],
        "UNKNOWN_TASK",
    ),
    (
        [block(1, at(12, 18), at(12, 19))],
        [task(1, 60)],
        "OUTSIDE_FREE_TIME",
    ),
    (
        [block(1, at(12, 14), at(12, 15))],
        [task(1, 60, deadline=at(12, 12))],
        "MISSED_DEADLINE",
    ),
    (
        [block(1, at(12, 9), at(12, 10)),
         block(2, at(12, 9, 30), at(12, 10, 30))],
        [task(1, 60), task(2, 60)],
        "OVERLAP_BLOCK",
    ),
    (
        [block(1, at(12, 9), at(12, 11))],
        [task(1, 60)],
        "TOO_MANY_MINUTES",
    ),
])
def test_each_violation_type(blocks, tasks, expected):
    assert expected in types(
        validate_plan(blocks, tasks, [], WINDOWS, NOW)
    )


def test_block_in_the_past():
    blocks = [block(1, at(12, 9), at(12, 10))]

    violations = validate_plan(blocks, [task(1, 60)], [], WINDOWS, at(12, 12))

    assert types(violations) == ["IN_PAST"]


def test_overlap_with_fixed_event():
    events = [{"title": "Class", "start": at(12, 9), "end": at(12, 10),
               "editable": False, "all_day": False}]
    blocks = [block(1, at(12, 9, 30), at(12, 10, 30))]

    violations = validate_plan(blocks, [task(1, 60)], events, WINDOWS, NOW)

    assert types(violations) == ["OVERLAP_FIXED"]
    assert violations[0]["task_id"] == 1


def test_validator_accepts_dict_blocks():
    blocks = [{"task_id": 1, "start": "2026-10-12T09:00:00",
               "end": "2026-10-12T10:00:00"}]

    assert validate_plan(blocks, [task(1, 60)], [], WINDOWS, NOW) == []
