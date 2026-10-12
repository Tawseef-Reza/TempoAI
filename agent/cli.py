"""TempoAI in the terminal.

You update your tasks with commands (no AI involved); anything you type
that isn't a command goes to TempoAI, which makes a complete plan. Nothing
changes on the calendar until you /apply.

Run:  python -m agent.cli      (type /help for commands)
"""

import shlex
from datetime import datetime, timedelta

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

HELP = """\
Tasks (instant, no AI):
  /add                          add a task (asks for each field)
  /edit <id> <field> <value>    field: title | deadline | priority | remaining
  /done <id>                    mark a task complete
  /delete <id>                  delete a task
  /tasks                        list tasks
  /prefs [text | clear]         show or set standing preferences for the AI,
                                e.g. /prefs no work before 10am
Schedule:
  <any message>                 ask TempoAI for a plan, e.g. "plan my week",
                                "essay first, nothing on Friday"
  /apply  /discard              accept or drop TempoAI's plan
  /calendar [days]              show the calendar (and any plan)
Time and calendar:
  /now [YYYY-MM-DD HH:MM]       show or set the simulated time
  /persona <worker_9_5 | college_student | vacation | custom>   load a month
  /event add "<title>" <YYYY-MM-DD HH:MM> <YYYY-MM-DD HH:MM>
  /event remove <e#>            add/remove fixed events (custom month only)
  /help  /quit"""

# The terminal has one user; a hosted app would pass its session ID.
USER_KEY = "local"

EDIT_FIELDS = {
    "title": "title", "deadline": "deadline", "priority": "priority",
    "remaining": "remaining_minutes", "minutes": "remaining_minutes",
}


class Session:
    def __init__(self):
        db.init_db()
        self.calendar = get_calendar()
        self.history = None
        self.plan = None

    # ---------- helpers ----------

    def now(self):
        return clock.get_now()

    def fixed_labels(self):
        """{event_id: "e1", ...} for every fixed event, in time order."""
        fixed = [e for e in self.calendar.get_events() if not e["editable"]]
        return {e["id"]: f"e{n}" for n, e in enumerate(fixed, 1)}

    def drop_stale_plan(self):
        if self.plan is not None:
            self.plan = None
            print("(The held plan was discarded because things changed. "
                  "Ask TempoAI again.)")

    # ---------- commands ----------

    def cmd_add(self, args):
        title = input("  Title: ").strip()
        minutes = input("  Minutes of work left: ").strip()
        deadline = input("  Deadline (YYYY-MM-DD [HH:MM], blank = none): ")
        priority = input("  Priority 1-5 (1 = highest, blank = 3): ").strip()
        task = task_actions.add_task(
            title, minutes, deadline.strip() or None, priority or 3
        )
        print(f"Added task {task['id']}: {task['title']}.")

    def cmd_edit(self, args):
        if len(args) < 3 or args[1] not in EDIT_FIELDS:
            raise ValueError("Usage: /edit <id> title|deadline|priority|"
                             "remaining <value>")
        field = EDIT_FIELDS[args[1]]
        value = " ".join(args[2:])
        if field == "deadline" and value.lower() in ("none", "-"):
            value = None
        task = task_actions.edit_task(args[0], **{field: value})
        print(f"Updated task {task['id']}: {task['title']}.")

    def cmd_done(self, args):
        task = task_actions.complete_task(args[0])
        print(f"Completed '{task['title']}'.")

    def cmd_delete(self, args):
        task = task_actions.delete_task(args[0])
        print(f"Deleted '{task['title']}'. Its blocks go away with the next "
              "plan you apply.")

    def cmd_tasks(self, args):
        tasks = db.get_tasks()
        if not tasks:
            print("No open tasks. Add one with /add.")
        for task in tasks:
            due = to_local(task["deadline"]).strftime("%a %b %d %H:%M") \
                if task["deadline"] else "-"
            print(f"  {task['id']:>3}  {task['title']:<30} "
                  f"{task['remaining_minutes']:>4} min  due {due:<16} "
                  f"priority {task['priority']}")

    def cmd_prefs(self, args):
        if not args:
            current = db.get_preferences()
            print(f"Preferences: {current}" if current else
                  "No preferences set. Example: /prefs no work before 10am, "
                  "at most 2 hours per task per day")
            return
        text = "" if args == ["clear"] else args[0]
        task_actions.set_preferences(text)
        print(f"Preferences set: {text}" if text else "Preferences cleared.")

    def cmd_apply(self, args):
        if self.plan is None:
            print("No plan to apply. Ask TempoAI first.")
            return
        removed, added = apply_plan(self.calendar, self.plan, self.now())
        self.plan = None
        # That planning round is finished. Starting fresh keeps requests
        # small; the next plan is made from the tasks as they are.
        self.history = None
        print(f"Applied: {removed} old blocks replaced by {added} new ones.")
        print(APPLY_HINT)

    def cmd_discard(self, args):
        self.plan = None
        self.history = None
        print("Plan discarded. Nothing changed.")

    def cmd_calendar(self, args):
        """The calendar; with a plan held, its blocks replace the upcoming
        TempoAI blocks (marked +)."""
        days = int(args[0]) if args else 7
        now = self.now()
        start = now.replace(hour=0, minute=0)
        end = start + timedelta(days=days)
        fixed_labels = self.fixed_labels()

        rows = []
        for event in self.calendar.get_events(start, end):
            if not event["editable"]:
                tag = f"[{fixed_labels[event['id']]}]"
            elif self.plan is not None and event["start"] >= now:
                continue  # replaced by the held plan
            else:
                tag = "[tempo]"
            rows.append((event["start"], event["end"], tag, event["title"]))
        if self.plan is not None:
            for block in self.plan.blocks:
                if start <= block.start < end:
                    rows.append((block.start, block.end, "+[plan]",
                                 block.title))

        print(f"Now: {now:%a %b %d %H:%M}"
              + ("   (+ = held plan)" if self.plan is not None else ""))
        current_day = None
        for row_start, row_end, tag, title in sorted(rows,
                                                     key=lambda r: r[0]):
            if row_start.date() != current_day:
                current_day = row_start.date()
                print(f"\n{row_start:%A %b %d}")
            print(f"  {row_start:%H:%M}-{row_end:%H:%M}  {tag:<10} {title}")
        if not rows:
            print("No events in this range.")

    def cmd_now(self, args):
        if args:
            clock.set_now(" ".join(args).replace(" ", "T", 1))
            self.drop_stale_plan()
        print(f"Now: {self.now():%a %b %d %Y %H:%M} (simulated)")

    def cmd_persona(self, args):
        if not args or args[0] not in TEMPLATES:
            raise ValueError(f"Choose one of: {', '.join(TEMPLATES)}")
        count = load_template(self.calendar, args[0])
        self.plan = None
        self.history = None
        print(f"Loaded '{TEMPLATES[args[0]]['label']}' with {count} fixed "
              f"events. Now: {self.now():%a %b %d %H:%M}")

    def cmd_event(self, args):
        if loaded_template() != "custom":
            raise ValueError("Fixed events can only be changed in the "
                             "custom month: /persona custom")
        if args[:1] == ["add"] and len(args) in (4, 6):
            title, times = args[1], args[2:]
            if len(times) == 4:  # date and time given as separate words
                times = [f"{times[0]} {times[1]}", f"{times[2]} {times[3]}"]
            start, end = (datetime.fromisoformat(t) for t in times)
            check_in_month(start, end)
            event = self.calendar.add_fixed_event(title, start, end)
            print(f"Added fixed event '{event['title']}': "
                  f"{event['start']:%a %b %d %H:%M}-{event['end']:%H:%M}")
        elif args[:1] == ["remove"] and len(args) == 2:
            ids = {label: event_id
                   for event_id, label in self.fixed_labels().items()}
            if args[1] not in ids:
                raise ValueError(f"No fixed event {args[1]} "
                                 "(see the e# labels in /calendar).")
            self.calendar.remove_fixed_event(ids[args[1]])
            print(f"Removed fixed event {args[1]}.")
        else:
            raise ValueError('Usage: /event add "<title>" <YYYY-MM-DD HH:MM> '
                             '<YYYY-MM-DD HH:MM>  |  /event remove <e#>')

    # ---------- talking to TempoAI ----------

    def ask(self, message):
        try:
            plan = make_plan(message, self.calendar, self.history,
                             now=self.now(), user_key=USER_KEY)
        except limits.LimitReached as exc:
            print(f"! {exc}")
            return
        except Exception as exc:  # network, auth or quota errors
            text = str(exc).lower()
            if "authentication" in text or "api_key" in text \
                    or "api key" in text:
                print("! No API key found. Add ANTHROPIC_API_KEY=... (or "
                      "GEMINI_API_KEY=...) to your .env file.")
            else:
                print(f"! TempoAI couldn't reach the AI model: {exc}")
            return
        self.history = plan.history

        if not plan.ok:
            self.plan = None
            print("\ntempo> I couldn't make a plan that follows the rules:")
            for error in plan.errors:
                print(f"  - {error}")
            return
        if not plan.blocks:
            self.plan = None
            print("\ntempo> Nothing to plan.")
            return

        self.plan = plan
        current_day = None
        for block in plan.blocks:
            if block.start.date() != current_day:
                current_day = block.start.date()
                print(f"\n{block.start:%A %b %d}")
            print(f"  {block.start:%H:%M}-{block.end:%H:%M}  {block.title}")
        for line in didnt_fit_lines(plan, self.now()):
            print(f"  ! {line}")
        print("\n/apply to accept, /discard to drop, /calendar to preview.")

    # ---------- loop ----------

    COMMANDS = {
        "/add": "cmd_add", "/edit": "cmd_edit", "/done": "cmd_done",
        "/delete": "cmd_delete", "/tasks": "cmd_tasks", "/prefs": "cmd_prefs",
        "/apply": "cmd_apply", "/discard": "cmd_discard",
        "/calendar": "cmd_calendar", "/now": "cmd_now",
        "/persona": "cmd_persona", "/event": "cmd_event",
    }
    # These make a held plan out of date.
    CHANGES_PLAN = {"/add", "/edit", "/done", "/delete", "/prefs", "/event"}

    def run(self):
        print("TempoAI. /help for commands.")
        if loaded_template() is None:
            print("Start by loading a month, e.g. /persona college_student")
        while True:
            print()
            if self.plan is not None:
                print("  A plan is waiting: /calendar to preview, /apply or "
                      "/discard.")
            # Piped input on Windows can start with a byte-order mark.
            line = input("you> ").strip().lstrip("﻿")
            if not line:
                continue
            if line == "/quit":
                break
            if line == "/help":
                print(HELP)
                continue
            if not line.startswith("/"):
                self.ask(line)
                continue

            name = line.split()[0]
            if name == "/prefs":
                # Free text: keep it as typed (apostrophes and all).
                rest = line[len(name):].strip()
                args = [rest] if rest else []
            else:
                parts = shlex.split(line)
                args = parts[1:]
            method = self.COMMANDS.get(name)
            if method is None:
                print("Unknown command. Type /help.")
                continue
            try:
                getattr(self, method)(args)
            except (ValueError, IndexError, KeyError,
                    PermissionError) as exc:
                print(f"! {exc}" if str(exc) else "! Missing arguments.")
                continue
            if name in self.CHANGES_PLAN:
                self.drop_stale_plan()


def main():
    Session().run()


if __name__ == "__main__":
    main()
