from __future__ import annotations

import argparse
from pathlib import Path

from .runtime import create_dry_run, run_only


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-factory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Start a factory run")
    run.add_argument("feature", type=Path, help="Product brief markdown file")
    run.add_argument("--config", type=Path, default=Path("factory.yaml"))
    run.add_argument("--dry-run", action="store_true", help="Create run artifacts without workers")
    run.add_argument(
        "--only",
        choices=["planner", "architect", "task_generator"],
        help="Run workers up to the selected role and stop at its gate",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        if args.dry_run and args.only:
            parser.error("--dry-run and --only cannot be used together")
        if args.dry_run:
            result = create_dry_run(args.feature, args.config)
        elif args.only:
            result = run_only(args.feature, args.config, args.only)
        else:
            parser.error("use --dry-run or --only planner|architect|task_generator")
        print(f"created run: {result.run_dir}")
        print(f"state: {result.state_file}")
        print(f"queue: {result.queue_file}")
        print(f"locks: {result.locks_file}")
        print(f"events: {result.events_file}")
        if args.only:
            print(f"gate: {args.only}")
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
