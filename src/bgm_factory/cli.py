from __future__ import annotations

import argparse
import json

from .prompt import build_prompt
from .runtime import initialize_runtime
from .service import process_next_job


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BGM Factory control command")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db", help="create or migrate the SQLite database")
    enqueue = commands.add_parser("enqueue", help="enqueue a generation job")
    enqueue.add_argument("--theme", default=None)
    enqueue.add_argument("--count", type=int, default=1)
    commands.add_parser("run-once", help="process the next queued job")
    status = commands.add_parser("status", help="show queue and recent jobs")
    status.add_argument("--limit", type=int, default=10)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    paths, config, repository = initialize_runtime()
    if args.command == "init-db":
        print(repository.database_path)
        return
    if args.command == "enqueue":
        if args.count < 1:
            raise SystemExit("--count must be at least 1")
        theme = args.theme or config.generation.default_theme
        prompt, _ = build_prompt(theme, paths)
        job_id = repository.enqueue_job(theme, prompt, args.count)
        print(job_id)
        return
    if args.command == "run-once":
        result, decision = process_next_job(paths, config, repository)
        payload = {
            "result": result.__dict__ if result else None,
            "guard": decision.__dict__ if decision else None,
        }
        print(json.dumps(payload, default=str, indent=2))
        return
    print(
        json.dumps(
            {
                "queue": repository.queue_stats(),
                "recent_jobs": repository.recent_jobs(args.limit),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
