from __future__ import annotations

import argparse
from datetime import date
import logging
from pathlib import Path

from .backtest import fetch_history, run_backtest, summarize
from .config import WEBHOOK_ENV_VAR, load_config
from .notifier import Notification
from .service import SLOTS, build_default_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan when to open the windows and post the plan to Discord.")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the scheduler: morning plan, midday update, evening plan.")
    run_parser.add_argument("--config", type=Path, required=True, help="Path to the TOML config file.")

    plan_parser = subparsers.add_parser("plan", help="Print the plan message for right now.")
    plan_parser.add_argument("--config", type=Path, required=True, help="Path to the TOML config file.")
    plan_parser.add_argument("--slot", choices=SLOTS, default="morning", help="Which message to build.")
    plan_parser.add_argument("--send", action="store_true", help="Also post it to Discord (does not change saved state).")

    backtest_parser = subparsers.add_parser("backtest", help="Replay past weather through the planner.")
    backtest_parser.add_argument("--config", type=Path, required=True, help="Path to the TOML config file.")
    backtest_parser.add_argument("--start", type=date.fromisoformat, required=True, help="First day (YYYY-MM-DD).")
    backtest_parser.add_argument("--end", type=date.fromisoformat, required=True, help="Last day (YYYY-MM-DD).")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = load_config(args.config)
    needs_webhook = args.command == "run" or (args.command == "plan" and args.send)
    if needs_webhook and not config.discord_webhook_url:
        parser.error(f"Set {WEBHOOK_ENV_VAR} (or discord_webhook_url in the config) to send Discord messages.")

    if args.command == "run":
        build_default_service(config).run_forever()
        return 0

    if args.command == "plan":
        service = build_default_service(config)
        state = service.dependencies.state_store.load()
        result = service.prepare(args.slot, service.now(), state)
        print(result.message or "(No message: the plan has not changed since the last one sent.)")
        if args.send and result.message:
            service.dependencies.notifier.send(Notification(body=result.message, mention=config.discord_mention))
        return 0

    if args.command == "backtest":
        series = fetch_history(config, args.start, args.end)
        print(summarize(run_backtest(config, series, args.start, args.end)))
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
