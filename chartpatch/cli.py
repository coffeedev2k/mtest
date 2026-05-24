from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .dependencies import MissingRuntimeDependencies, check_required_binaries
from .plan import build_plan
from .report import render_plan
from .workflow import (
    STAGE_DEPENDENCY_CHECK,
    SyncWorkflowError,
    render_sync_failure_report,
    render_sync_report,
    run_sync,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chartpatch")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Print a side-effect-free chart execution plan")
    plan.add_argument("config", type=Path, help="YAML config file")

    sync = subparsers.add_parser("sync", help="Pull and render the configured chart")
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
            if config.is_multi_chart:
                raise ConfigError("multi-chart sync is not implemented yet")
            check_required_binaries()
            result = run_sync(config)
        except ConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        except MissingRuntimeDependencies as exc:
            print(
                render_sync_failure_report(
                    SyncWorkflowError(
                        str(exc),
                        stage=STAGE_DEPENDENCY_CHECK,
                        source_repo=config.chart.source.repo,
                        source_chart=config.chart.source.chart,
                        source_version=config.chart.source.version,
                    )
                ),
                end="",
                file=sys.stderr,
            )
            return 1
        except SyncWorkflowError as exc:
            print(render_sync_failure_report(exc), end="", file=sys.stderr)
            return 1
        print(render_sync_report(result), end="")
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2
