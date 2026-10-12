"""TempoAI in the browser.

Each visitor gets their own tasks and calendar (a small database per
session); the AI usage limits are shared by everyone.

Run:  streamlit run app.py
"""

import hashlib
import json
import time
from datetime import datetime, timedelta
from uuid import uuid4

import streamlit as st
from streamlit_calendar import calendar as calendar_view

from agent import clock, limits, task_actions
from agent.apply import apply_plan
from agent.planner import APPLY_HINT, didnt_fit_lines, make_plan
from calendar_integration.templates import (
    TEMPLATES,
    check_in_month,
    load_template,
    loaded_template,
)
from config import get_calendar
from database import db
from scheduling.scheduler import to_local

SESSION_MAX_AGE_DAYS = 2
FIXED, APPLIED, PLANNED = "#9aa0a6", "#4a7bd0", "#2e9e5b"

st.set_page_config(page_title="TempoAI", layout="wide")


# ---------- per-visitor state ----------

@st.cache_resource
def remove_old_sessions():
    """Once per server start: delete visitor databases nobody has used for
    a while."""
    cutoff = time.time() - SESSION_MAX_AGE_DAYS * 86400
    folder = db.sessions_dir()
    if folder.exists():
        for path in folder.glob("*.db"):
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)


remove_old_sessions()
state = st.session_state
state.setdefault("sid", uuid4().hex)
state.setdefault("history", None)
state.setdefault("plan", None)
state.setdefault("last", None)    # (message, reply lines, kind)
state.setdefault("flash", None)   # (kind, text) shown after a rerun
db.use_session_db(db.sessions_dir() / f"{state.sid}.db")
cal = get_calendar()


def done(text, kind="success", drop_plan=True):
    """Finish an action: show a message after the rerun and, if the
    action changed tasks/time/events, drop the now-stale plan."""
    if drop_plan and state.plan is not None:
        state.plan = None
        text += " (The held plan was dropped because things changed.)"
    state.flash = (kind, text)
    st.rerun()


def guarded(action):
    """Run an action, turning input mistakes into an error message."""
    try:
        action()
    except (ValueError, KeyError, PermissionError) as exc:
        st.sidebar.error(str(exc) or "Missing or invalid input.")


# ---------- sidebar ----------

def month_section():
    st.sidebar.header("Month")
    names = list(TEMPLATES)
    current = loaded_template()
    choice = st.sidebar.selectbox(
        "Calendar", names, index=names.index(current) if current else 0,
        format_func=lambda n: TEMPLATES[n]["label"], key="month",
    )
    if st.sidebar.button("Load month", key="load"):
        count = load_template(cal, choice)
        state.history = None
        done(f"Loaded '{TEMPLATES[choice]['label']}' with {count} fixed "
             "events.")


def time_section(now):
    st.sidebar.header("Time")
    st.sidebar.caption(f"Now: {now:%a %b %d %Y, %H:%M} (simulated)")
    col1, col2 = st.sidebar.columns(2)
    day = col1.date_input("Date", now.date(), key="now_date")
    at = col2.time_input("Time", now.time(), step=900, key="now_time")
    if st.sidebar.button("Set time", key="set_time"):
        clock.set_now(datetime.combine(day, at))
        done("Time updated.")


def prefs_section():
    st.sidebar.header("Preferences")
    with st.sidebar.form("prefs"):
        text = st.text_area("Lasting rules for the AI",
                            db.get_preferences() or "",
                            placeholder="e.g. no work before 10am")
        if st.form_submit_button("Save"):
            task_actions.set_preferences(text)
            done("Preferences saved.")


def deadline_text(task):
    return to_local(task["deadline"]).strftime("%Y-%m-%d %H:%M") \
        if task["deadline"] else ""


def tasks_section():
    st.sidebar.header("Tasks")
    for task in db.get_tasks():
        due = deadline_text(task) or "no deadline"
        label = f"{task['title']} · {task['remaining_minutes']} min · {due}"
        with st.sidebar.expander(label):
            with st.form(f"task_{task['id']}"):
                title = st.text_input("Title", task["title"])
                minutes = st.number_input("Minutes left", 0, 10000,
                                          task["remaining_minutes"], 15)
                deadline = st.text_input("Deadline (YYYY-MM-DD HH:MM)",
                                         deadline_text(task))
                priority = st.number_input("Priority (1 = highest)", 1, 5,
                                           task["priority"])
                save, finish, delete = st.columns(3)
                if save.form_submit_button("Save"):
                    guarded(lambda: (task_actions.edit_task(
                        task["id"], title=title, remaining_minutes=minutes,
                        deadline=deadline.strip() or None,
                        priority=priority), done("Task saved.")))
                if finish.form_submit_button("Done"):
                    task_actions.complete_task(task["id"])
                    done(f"Completed '{task['title']}'.")
                if delete.form_submit_button("Delete"):
                    task_actions.delete_task(task["id"])
                    done(f"Deleted '{task['title']}'.")

    with st.sidebar.form("add_task", clear_on_submit=True):
        st.markdown("**Add a task**")
        title = st.text_input("Title", key="new_title")
        minutes = st.number_input("Minutes of work", 15, 10000, 60, 15,
                                  key="new_minutes")
        deadline = st.text_input("Deadline (YYYY-MM-DD HH:MM, blank = none)",
                                 key="new_deadline")
        priority = st.number_input("Priority (1 = highest)", 1, 5, 3,
                                   key="new_priority")
        if st.form_submit_button("Add task"):
            guarded(lambda: (task_actions.add_task(
                title, minutes, deadline.strip() or None, priority),
                done(f"Added '{title.strip()}'.")))


def events_section(now):
    st.sidebar.header("Fixed events")
    fixed = [e for e in cal.get_events() if not e["editable"]]
    for event in fixed:
        text, remove = st.sidebar.columns([5, 1])
        text.caption(f"{event['start']:%a %b %d %H:%M}-{event['end']:%H:%M}"
                     f" · {event['title']}")
        if remove.button("✕", key=f"rm_{event['id']}"):
            cal.remove_fixed_event(event["id"])
            done(f"Removed '{event['title']}'.")

    with st.sidebar.form("add_event", clear_on_submit=True):
        st.markdown("**Add a fixed event**")
        title = st.text_input("Title", key="event_title")
        day = st.date_input("Date", now.date(), key="event_date")
        col1, col2 = st.columns(2)
        start = col1.time_input("Start", datetime.min.replace(hour=9).time(),
                                step=900, key="event_start")
        end = col2.time_input("End", datetime.min.replace(hour=10).time(),
                              step=900, key="event_end")
        if st.form_submit_button("Add event"):
            def add():
                if not title.strip():
                    raise ValueError("An event needs a title.")
                begin = datetime.combine(day, start)
                finish = datetime.combine(day, end)
                check_in_month(begin, finish)
                cal.add_fixed_event(title.strip(), begin, finish)
                done(f"Added '{title.strip()}'.")
            guarded(add)


# ---------- main area ----------

def stamp(moment):
    """Local wall-clock time without an offset, so the calendar shows it
    as-is whatever the visitor's timezone."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S")


def calendar_events(now):
    events = []
    for event in cal.get_events():
        if not event["editable"]:
            color = FIXED
        elif state.plan is not None and event["start"] >= now:
            continue  # replaced by the held plan
        else:
            color = APPLIED
        events.append({"title": event["title"], "start": stamp(event["start"]),
                       "end": stamp(event["end"]), "color": color})
    if state.plan is not None:
        for block in state.plan.blocks:
            events.append({"title": block.title, "start": stamp(block.start),
                           "end": stamp(block.end), "color": PLANNED})
    return events


def show_calendar(now):
    template = db.get_setting("template")
    events = calendar_events(now)
    options = {
        "initialView": "timeGridWeek",
        "initialDate": now.date().isoformat(),
        "firstDay": 1,
        "headerToolbar": {"left": "prev,next", "center": "title",
                          "right": "timeGridWeek,dayGridMonth,listWeek"},
        "slotMinTime": "06:00:00",
        "slotMaxTime": "24:00:00",
        "allDaySlot": False,
        "nowIndicator": False,
        "height": 680,
        "validRange": {"start": template["start"], "end": template["end"]},
    }
    digest = hashlib.md5(json.dumps([events, options]).encode()).hexdigest()
    calendar_view(events=events, options=options, callbacks=[],
                  key=f"cal_{digest}")
    st.caption("Grey: fixed events · Blue: your applied plan · "
               "Green: TempoAI's new plan (not applied yet)")


def plan_panel(now):
    plan = state.plan
    st.success(f"TempoAI's plan has {len(plan.blocks)} blocks (green). "
               "Apply it to put it on your calendar.")
    for line in didnt_fit_lines(plan, now):
        st.warning(line)
    apply_col, discard_col, _ = st.columns([1, 1, 4])
    if apply_col.button("Apply", type="primary", key="apply"):
        removed, added = apply_plan(cal, plan, now)
        state.plan, state.history = None, None
        done(f"Applied: {removed} old blocks replaced by {added} new ones. "
             f"{APPLY_HINT}", drop_plan=False)
    if discard_col.button("Discard", key="discard"):
        state.plan, state.history = None, None
        done("Plan discarded. Nothing changed.", kind="info", drop_plan=False)


def ask(message, now):
    try:
        plan = make_plan(message, cal, state.history, now=now,
                         user_key=state.sid)
    except limits.LimitReached as exc:
        state.last = (message, [str(exc)], "error")
        return
    except Exception as exc:  # network, auth or quota errors
        text = str(exc).lower()
        if "authentication" in text or "api_key" in text or "api key" in text:
            reply = "The app has no working AI key right now."
        else:
            reply = f"TempoAI couldn't reach the AI model: {exc}"
        state.last = (message, [reply], "error")
        return

    state.history = plan.history
    if not plan.ok:
        state.plan = None
        state.last = (message, ["I couldn't make a plan that follows the "
                                "rules:"] + plan.errors, "error")
    elif not plan.blocks:
        state.plan = None
        state.last = (message, ["Nothing to plan. Add some tasks first."],
                      "info")
    else:
        state.plan = plan
        state.last = (message, ["Here's a plan; it's shown in green on the "
                                "calendar."], "success")


def chat(now):
    if state.last:
        message, lines, kind = state.last
        st.chat_message("user").write(message)
        with st.chat_message("assistant"):
            getattr(st, kind)("\n\n".join(lines))
    message = st.chat_input("Ask TempoAI for a plan, e.g. \"plan my week, "
                            "nothing after 9pm\"")
    if message:
        with st.spinner("Planning..."):
            ask(message, now)
        st.rerun()


# ---------- page ----------

st.title("TempoAI")
if state.flash:
    kind, text = state.flash
    getattr(st, kind)(text)
    state.flash = None

month_section()
if loaded_template() is None:
    st.info("Pick a month in the sidebar and press **Load month** to start.")
    st.stop()

now = clock.get_now()
time_section(now)
prefs_section()
tasks_section()
if loaded_template() == "custom":
    events_section(now)

show_calendar(now)
if state.plan is not None:
    plan_panel(now)
chat(now)
