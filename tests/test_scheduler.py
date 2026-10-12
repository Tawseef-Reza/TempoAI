from datetime import datetime

from scheduling.scheduler import (
    Window,
    busy_from_events,
    expand_weekly_availability,
    free_slots,
    to_local,
)

# Monday 2026-10-12 is the reference week.
NOW = to_local(datetime(2026, 10, 12, 8, 0))


def at(day, hour, minute=0):
    return to_local(datetime(2026, 10, day, hour, minute))


def event(start, end, editable=False, all_day=False):
    return {"start": start, "end": end, "editable": editable,
            "all_day": all_day}


def test_weekly_availability_varies_by_day():
    pattern = {
        0: [("19:00", "22:00")],                    # Monday evening
        1: [("07:00", "09:00"), ("20:00", "21:00")],  # Tuesday
    }
    windows = expand_weekly_availability(pattern, at(12, 0), at(14, 0))

    assert windows == [
        Window(at(12, 19), at(12, 22)),
        Window(at(13, 7), at(13, 9)),
        Window(at(13, 20), at(13, 21)),
    ]


def test_window_crossing_midnight():
    windows = expand_weekly_availability(
        {0: [("22:00", "01:00")]}, at(12, 0), at(14, 0)
    )

    assert windows == [Window(at(12, 22), at(13, 1))]


def test_only_fixed_timed_events_are_busy():
    busy = busy_from_events([
        event(at(12, 9), at(12, 11)),
        event(at(12, 11), at(12, 12), editable=True),  # a TempoAI block
        event(at(12, 0), at(13, 0), all_day=True),
    ])

    assert busy == [Window(at(12, 9), at(12, 11))]


def test_free_slots_subtract_busy_time_and_the_past():
    slots = free_slots(
        [Window(at(12, 9), at(12, 17))],
        [Window(at(12, 10), at(12, 11))],
        at(12, 9, 30),
    )

    assert slots == [Window(at(12, 9, 30), at(12, 10)),
                     Window(at(12, 11), at(12, 17))]


def test_mixed_naive_and_aware_inputs():
    busy = busy_from_events([
        event("2026-10-12T09:00:00", "2026-10-12T10:00:00"),
    ])
    aware_window = [Window(
        datetime.fromisoformat("2026-10-12T09:00:00").astimezone(),
        datetime.fromisoformat("2026-10-12T17:00:00").astimezone(),
    )]

    slots = free_slots(aware_window, busy, datetime(2026, 10, 12, 8))

    assert slots == [Window(at(12, 10), at(12, 17))]
