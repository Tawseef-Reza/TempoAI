"""Time helpers used across TempoAI: to_local, Window, free_slots,
busy_from_events, expand_weekly_availability, ..."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta


# ---------- data shapes ----------

@dataclass
class Window:
    start: datetime
    end: datetime


@dataclass
class ProposedBlock:
    task_id: int
    title: str
    start: datetime
    end: datetime

    @property
    def minutes(self):
        return minutes_between(self.start, self.end)


# ---------- time helpers ----------

def to_local(value):
    """Parse ISO strings and make naive datetimes timezone-aware (naive
    values are interpreted as system local time)."""
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        return value.astimezone()
    return value


def minutes_between(start, end):
    return int((end - start).total_seconds() // 60)


def get_field(obj, name, default=None):
    """Read a field from either a dict (calendar event, DB row) or object."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _parse_clock(value):
    if isinstance(value, time):
        return value
    return time.fromisoformat(value)


def expand_weekly_availability(pattern, start, end):
    """Turn a weekly pattern into concrete windows between start and end.

    pattern maps weekday (0=Mon .. 6=Sun) to a list of ("HH:MM", "HH:MM")
    ranges, e.g. {0: [("07:00", "10:00"), ("19:00", "23:30")]}. A range
    whose end is not after its start crosses midnight.
    """
    start = to_local(start)
    end = to_local(end)
    windows = []

    day = start.date() - timedelta(days=1)  # catch ranges crossing midnight
    while day <= end.date():
        for open_at, close_at in pattern.get(day.weekday(), []):
            open_at = _parse_clock(open_at)
            close_at = _parse_clock(close_at)
            w_start = to_local(datetime.combine(day, open_at))
            close_day = day if close_at > open_at else day + timedelta(days=1)
            w_end = to_local(datetime.combine(close_day, close_at))

            w_start = max(w_start, start)
            w_end = min(w_end, end)
            if w_end > w_start:
                windows.append(Window(w_start, w_end))
        day += timedelta(days=1)

    return _merge(windows)


def _merge(windows):
    merged = []
    for window in sorted(windows, key=lambda w: w.start):
        if merged and window.start <= merged[-1].end:
            merged[-1].end = max(merged[-1].end, window.end)
        else:
            merged.append(Window(window.start, window.end))
    return merged


def fixed_events(events):
    """Fixed commitments: non-editable, timed events. All-day events are
    ignored, as calendars show them as "free" by default."""
    return [
        event for event in events
        if not get_field(event, "editable", False)
        and not get_field(event, "all_day", False)
    ]


def busy_from_events(events):
    """Busy intervals from fixed events. TempoAI's own blocks are not busy:
    a new plan replaces them."""
    return _merge([
        Window(to_local(get_field(event, "start")),
               to_local(get_field(event, "end")))
        for event in fixed_events(events)
    ])


def free_slots(windows, busy, now):
    """Availability windows minus busy time and anything before now."""
    now = to_local(now)
    slots = []

    for window in _merge(windows):
        pieces = [Window(max(window.start, now), window.end)]
        for interval in busy:
            next_pieces = []
            for piece in pieces:
                if interval.end <= piece.start or interval.start >= piece.end:
                    next_pieces.append(piece)
                    continue
                if interval.start > piece.start:
                    next_pieces.append(Window(piece.start, interval.start))
                if interval.end < piece.end:
                    next_pieces.append(Window(interval.end, piece.end))
            pieces = next_pieces
        slots.extend(p for p in pieces if p.end > p.start)

    return _merge(slots)
