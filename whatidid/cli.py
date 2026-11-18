"""CLI: `whatidid` serves the app, and can grade or export from a terminal.

    python -m whatidid              # serve on 127.0.0.1:8765 and open the browser
    python -m whatidid --no-open    # serve without opening a browser
    python -m whatidid grade        # write this week's report from the terminal
    python -m whatidid export md    # dump everything as markdown to stdout
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from .config import DEFAULT_DATA_DIR, Settings
from .store import Store, week_key


def _free_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]


def _open_later(url: str, delay: float = 0.8) -> None:
    def go() -> None:
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    threading.Thread(target=go, daemon=True).start()


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .server import create_app

    data_dir = Path(args.data).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    port = _free_port(args.port) if args.port else 8765
    url = f"http://{args.host}:{port}"
    print(f"What I Did {url}")
    print(f"  data folder: {data_dir}")
    print("  Ctrl+C to stop.")
    if args.open:
        _open_later(url)
    uvicorn.run(create_app(data_dir), host=args.host, port=port, log_level=args.log_level)
    return 0


def cmd_grade(args: argparse.Namespace) -> int:
    from . import graders

    store = Store(Path(args.data).expanduser())
    settings = Settings.load(store.root)
    iso = args.week or week_key(datetime.now())
    result = graders.grade_week(store, settings, iso)
    print(result["markdown"])
    if result.get("error"):
        print(f"\n[model grader failed, used the offline analyser: {result['error']}]", file=sys.stderr)
    print(f"\n[saved to {store.report_path(iso)}]", file=sys.stderr)
    return 0


def cmd_month(args: argparse.Namespace) -> int:
    from . import graders

    store = Store(Path(args.data).expanduser())
    settings = Settings.load(store.root)
    result = graders.grade_month(store, settings, args.month)
    print(result["markdown"])
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    store = Store(Path(args.data).expanduser())
    if args.format == "md":
        sys.stdout.write(store.export_markdown())
    else:
        json.dump(store.export_bundle(), sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from . import schedule

    store = Store(Path(args.data).expanduser())
    settings = Settings.load(store.root)
    state = schedule.due_state(settings, datetime.now())
    iso = week_key(datetime.now())
    week = store.read_week(iso)
    print(f"data:        {store.root}")
    print(f"week:        {iso}  ({len(week.entries)} entries)")
    print(f"question:    {'DUE' if state['due'] else 'not due'}"
          + (f" (paused: {state['paused']})" if state["paused"] else ""))
    print(f"next due:    {state['next_due_at']}")
    print(f"interval:    every {settings.interval_minutes} min, "
          f"{settings.active_start}–{settings.active_end}")
    print(f"grader:      {settings.grader} ({settings.llm_provider}/{settings.llm_model})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="whatidid", description="It interrupts you and asks what you're doing.")
    parser.add_argument("--data", default=str(DEFAULT_DATA_DIR), help="folder for the log files")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data", default=argparse.SUPPRESS, help="folder for the log files")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", parents=[common], help="run the local app (default)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--no-open", dest="open", action="store_false")
    serve.add_argument("--log-level", default="warning")
    serve.set_defaults(func=cmd_serve, open=True)

    grade = sub.add_parser("grade", parents=[common], help="write this week's report now")
    grade.add_argument("--week", default=None, help="2026-W47 or a date")
    grade.set_defaults(func=cmd_grade)

    month = sub.add_parser("month", parents=[common], help="write the month's report now")
    month.add_argument("--month", default=None, help="2026-11")
    month.set_defaults(func=cmd_month)

    export = sub.add_parser("export", parents=[common], help="dump everything to stdout")
    export.add_argument("format", choices=("json", "md"), nargs="?", default="json")
    export.set_defaults(func=cmd_export)

    status = sub.add_parser("status", parents=[common], help="show the clock and the folder")
    status.set_defaults(func=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        args = parser.parse_args((argv or []) + ["serve"])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
