from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .dependencies import MissingRuntimeDependencies, check_required_binaries
from .plan import build_plan
from .report import render_plan
from .workflow import build_sync_summary, render_sync_summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chartpatch")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Print a side-effect-free chart execution plan")
    plan.add_argument("config", type=Path, help="YAML config file")

    sync = subparsers.add_parser("sync", help="Print a dry chart sync workflow summary")
    sync.add_argument("config", type=Path, help="YAML config file")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "plan":
        try:
            config = load_config(args.config)
        except ConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(render_plan(build_plan(config)), end="")
        return 0

    if args.command == "sync":
        try:
            config = load_config(args.config)
            check_required_binaries()
        except ConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        except MissingRuntimeDependencies as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(render_sync_summary(build_sync_summary(config)), end="")
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2
