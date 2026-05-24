from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import ConfigError, load_config, normalize_chart_entries
from .dependencies import MissingRuntimeDependencies, check_required_binaries
from .plan import build_plan
from .report import render_plan
from .workflow import (
    STAGE_DEPENDENCY_CHECK,
    SyncWorkflowError,
    aggregate_chart_sync_reports,
    build_failed_chart_sync_report,
    build_successful_chart_sync_report,
    render_chart_sync_report,
    render_sync_failure_report,
    render_sync_report,
    run_single_chart_sync,
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
            charts = normalize_chart_entries(config)
            check_required_binaries()
            if not config.is_multi_chart:
                result = run_single_chart_sync(charts[0])
                print(render_sync_report(result), end="")
                return 0

            reports = []
            for index, chart in enumerate(charts, start=1):
                print(
                    f"Processing chart {index}/{len(charts)}: {chart.chart_name}",
                    flush=True,
                )
                try:
                    result = run_single_chart_sync(chart)
                except SyncWorkflowError as exc:
                    report = build_failed_chart_sync_report(chart, exc)
                    reports.append(report)
                    print(render_chart_sync_report(report), end="", file=sys.stderr)
                    continue

                report = build_successful_chart_sync_report(chart, result)
                reports.append(report)
                print(render_chart_sync_report(report), end="", flush=True)

            aggregate = aggregate_chart_sync_reports(tuple(reports))
            if not aggregate.succeeded:
                return 1
        except ConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        except MissingRuntimeDependencies as exc:
            chart = charts[0]
            if config.is_multi_chart:
                print(
                    f"ChartPatch sync failed for chart: {chart.chart_name}",
                    file=sys.stderr,
                )
            print(
                render_sync_failure_report(
                    SyncWorkflowError(
                        str(exc),
                        stage=STAGE_DEPENDENCY_CHECK,
                        source_repo=chart.source_repo,
                        source_chart=chart.source_chart,
                        source_version=chart.source_version,
                    )
                ),
                end="",
                file=sys.stderr,
            )
            return 1
        except SyncWorkflowError as exc:
            if config.is_multi_chart:
                print(
                    f"ChartPatch sync failed for chart: {chart.chart_name}",
                    file=sys.stderr,
                )
            print(render_sync_failure_report(exc), end="", file=sys.stderr)
            return 1
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2
