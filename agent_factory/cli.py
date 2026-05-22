from __future__ import annotations

import argparse
from pathlib import Path

from .runtime import create_dry_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-factory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Start a factory run")
    run.add_argument("feature", type=Path, help="Product brief markdown file")
    run.add_argument("--config", type=Path, default=Path("factory.yaml"))
    run.add_argument("--dry-run", action="store_true", help="Create run artifacts without workers")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        if not args.dry_run:
            parser.error("only --dry-run is implemented in the first milestone")
        result = create_dry_run(args.feature, args.config)
        print(f"created run: {result.run_dir}")
        print(f"state: {result.state_file}")
        print(f"queue: {result.queue_file}")
        print(f"locks: {result.locks_file}")
        print(f"events: {result.events_file}")
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
