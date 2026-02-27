"""Simple scheduler for running `excel_query.update_orders_from_excel` periodically.

Usage as a script:

    # start scheduler (runs in foreground)
    python excel_scheduler.py start --input orders.xlsx --interval 3600

    # stop/pause scheduler (sets flag; the running process will exit after current sleep)
    python excel_scheduler.py stop

    # check status
    python excel_scheduler.py status

Control is handled via a small JSON file (`scheduler_state.json`) in the
current working directory. You may also edit that file manually: set
`"enabled": false` to pause, true to resume.  When the scheduler is
running it checks the file before each interval and will skip execution if
`enabled` is false.

The purpose of this module is to provide a lightweight way to run the
existing excel_query logic on a timetable without modifying the main
application.
"""

import argparse
import json
import os
import sys
import time
from typing import Optional

from excel_query import update_orders_from_excel

STATE_FILE = "scheduler_state.json"
DEFAULT_INTERVAL = 3600  # seconds (1 hour)


def load_state() -> dict:
    if os.path.isfile(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # default state
    return {"enabled": False}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def run_scheduler(
    input_path: str,
    output_path: Optional[str] = None,
    interval: float = DEFAULT_INTERVAL,
) -> None:
    """Begin the scheduling loop (runs until interrupted).

    The scheduler checks the state file before each run; if `enabled` is
    False the update is skipped but the loop continues.  To terminate the
    loop the user may press Ctrl-C or run ``excel_scheduler.py stop`` from
    another terminal, which will set `enabled` to False and allow the
    current iteration to finish.
    """

    if not os.path.isfile(input_path):
        print(f"输入文件不存在: {input_path}")
        sys.exit(1)

    state = load_state()
    state["enabled"] = True
    save_state(state)
    print(f"Scheduler started. state file: {STATE_FILE}")

    try:
        while True:
            state = load_state()
            if state.get("enabled"):
                try:
                    print(f"[{time.asctime()}] Running update...")
                    update_orders_from_excel(input_path, output_path=output_path)
                    print(f"[{time.asctime()}] Update finished.")
                except Exception as e:
                    print(f"Error during update: {e}")
            else:
                print(f"[{time.asctime()}] Scheduler paused (enabled=false).")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Scheduler interrupted by user; exiting.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Simple scheduler for excel_query module")
    sub = parser.add_subparsers(dest="command")

    start_parser = sub.add_parser("start", help="Start the scheduler")
    start_parser.add_argument("--input", required=True, help="Excel file to process")
    start_parser.add_argument(
        "--output", help="Output file path (optional, passed through)")
    start_parser.add_argument(
        "--interval", type=float, default=DEFAULT_INTERVAL,
        help="Seconds between runs (default: %(default)s)"
    )

    sub.add_parser("stop", help="Set enabled=false in state file (pauses scheduler)")
    sub.add_parser("status", help="Show current state")

    args = parser.parse_args()

    if args.command == "start":
        run_scheduler(args.input, output_path=args.output, interval=args.interval)
    elif args.command == "stop":
        state = load_state()
        state["enabled"] = False
        save_state(state)
        print(f"Scheduler state updated: {state}")
    elif args.command == "status":
        state = load_state()
        print(f"Scheduler state: {state}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
