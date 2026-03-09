from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .config import load_config
from .service import build_default_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Notify when it is a good time to open or close windows.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the window bot service loop.")
    run_parser.add_argument("--config", type=Path, required=True, help="Path to the TOML config file.")
    run_parser.add_argument(
        "--once",
        action="store_true",
        help="Run one poll cycle and exit.",
    )
    run_parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "run":
        config = load_config(args.config)
        service = build_default_service(config)
        if args.once:
            service.run_once()
        else:
            service.run_forever()
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
