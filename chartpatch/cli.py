from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .plan import render_plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chartpatch")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Print a side-effect-free chart execution plan")
    plan.add_argument("config", type=Path, help="YAML config file")

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
        print(render_plan(config), end="")
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2

