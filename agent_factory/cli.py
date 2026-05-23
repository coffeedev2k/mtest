from __future__ import annotations

import argparse
from pathlib import Path

from .runtime import build_feature, create_dry_run, run_only, run_parallel_tasks, run_task
from .status import render_status


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
    status = subparsers.add_parser("status", help="Show run status")
    status.add_argument("run_dir", type=Path)
    execute_task = subparsers.add_parser("execute-task", help="Run implementer, reviewer, and tester for one task")
    execute_task.add_argument("task", type=Path)
    execute_task.add_argument("--config", type=Path, default=Path("factory.yaml"))
    execute_tasks = subparsers.add_parser("execute-tasks", help="Run implementers for multiple tasks with write-scope locks")
    execute_tasks.add_argument("tasks", type=Path, nargs="+")
    execute_tasks.add_argument("--config", type=Path, default=Path("factory.yaml"))
    build = subparsers.add_parser("build", help="Plan, implement, review, test, and commit one task")
    build.add_argument("feature", type=Path)
    build.add_argument("--config", type=Path, default=Path("factory.yaml"))
    build.add_argument("--max-tasks", type=int, default=1, help="Number of sequential task cycles to run")
    build.add_argument("--no-commit", action="store_true", help="Run the build without creating a gate commit")

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

    if args.command == "status":
        print(render_status(args.run_dir), end="")
        return 0

    if args.command == "execute-task":
        result = run_task(args.task, args.config)
        print(f"created run: {result.run_dir}")
        print(f"state: {result.state_file}")
        print(f"queue: {result.queue_file}")
        print(f"locks: {result.locks_file}")
        print(f"events: {result.events_file}")
        print("gate: task_execution")
        return 0

    if args.command == "execute-tasks":
        result = run_parallel_tasks(args.tasks, args.config)
        print(f"created run: {result.run_dir}")
        print(f"state: {result.state_file}")
        print(f"queue: {result.queue_file}")
        print(f"locks: {result.locks_file}")
        print(f"events: {result.events_file}")
        print("gate: parallel_implementation")
        return 0

    if args.command == "build":
        result = build_feature(
            args.feature,
            args.config,
            commit=not args.no_commit,
            max_tasks=args.max_tasks,
        )
        for iteration in result.iterations:
            print(f"task cycle: {iteration.index}")
            print(f"planning run: {iteration.planning_run.run_dir}")
            print(f"execution run: {iteration.execution_run.run_dir}")
            print(f"task: {iteration.task_file}")
            if iteration.commit_sha:
                print(f"commit: {iteration.commit_sha}")
            elif args.no_commit:
                print("commit: skipped")
            else:
                print("commit: no changes")
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
