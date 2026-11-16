from __future__ import annotations

import argparse
import json
import logging
import os

from schedulermp.chain import ChainClient
from schedulermp.config import load_settings
from schedulermp.server import SchedulerApp, serve
from schedulermp.store import StateStore
from schedulermp.tdr import TdrClient


def load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, value = text.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def build_app() -> SchedulerApp:
    load_dotenv()
    settings = load_settings()
    store = StateStore(settings.state_path)
    return SchedulerApp(settings, TdrClient(settings), ChainClient(settings), store)


def configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        level = logging.INFO
        level_name = "INFO"
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    logging.getLogger("schedulermp").setLevel(level)
    logging.getLogger("schedulermp").info("log level %s", level_name)


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="TDR to MP blockchain scheduler")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve", help="run the HTTP API and enabled phase loops in this terminal")
    sub.add_parser("start", help="run serve in the background and restart it if it exits")
    sub.add_parser("stop", help="stop the background scheduler")
    sub.add_parser("restart", help="stop and start the background scheduler")
    sub.add_parser("status", help="show whether the background scheduler is running")
    logs = sub.add_parser("logs", help="show the background scheduler log")
    logs.add_argument("-f", "--follow", action="store_true", help="keep printing new log lines")
    sub.add_parser("install", help="install a systemd service that starts on boot")

    phase1 = sub.add_parser("phase1", help="verify DRC certificates against blockchain")
    phase1.add_argument("--certificate", default="")
    phase1.add_argument("--limit", type=int, default=0)

    phase2 = sub.add_parser("phase2", help="migrate legacy applications")
    phase2.add_argument("--application-id", default="")
    phase2.add_argument("--limit", type=int, default=0)
    phase2.add_argument("--force", action="store_true")

    phase3 = sub.add_parser("phase3", help="sync one live application, or poll new ones")
    phase3.add_argument("--application-id", default="")
    phase3.add_argument("--owner-id", action="append", default=[])
    phase3.add_argument("--certificate", action="append", default=[])
    phase3.add_argument("--limit", type=int, default=0)
    phase3.add_argument("--force", action="store_true")

    args = parser.parse_args(argv)
    if args.command in {"start", "stop", "restart", "status", "logs", "install"}:
        from schedulermp.keeper import run

        run(args)
        return
    configure_logging()
    app = build_app()
    if args.command == "serve":
        serve(app)
        return
    if args.command == "phase1":
        print_result(app.run_phase1(args.certificate, args.limit))
        return
    if args.command == "phase2":
        print_result(app.run_phase2(args.application_id, args.limit, args.force))
        return
    if args.command == "phase3":
        print_result(
            app.run_phase3(args.application_id, args.owner_id, args.certificate, args.force, args.limit)
        )


def print_result(payload: dict) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
