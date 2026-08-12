from __future__ import annotations

import argparse
import json
from pathlib import Path

from .prompt import build_prompt
from .runtime import initialize_runtime
from .service import process_next_job
from .short_renderer import ShortScene, render_short
from .youtube_analytics import collect_youtube_analytics
from .youtube_auth import authorization_summary, authorize, connection_status
from .youtube_uploader import register_video, upload_next


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
    youtube_auth = commands.add_parser("youtube-auth", help="authorize the YouTube channel")
    youtube_auth.add_argument(
        "--no-browser", action="store_true", help="print the authorization URL only"
    )
    commands.add_parser("youtube-status", help="verify the authorized YouTube channel")
    register = commands.add_parser("video-register", help="register a rendered video")
    register.add_argument("--file", type=Path, required=True)
    register.add_argument("--kind", choices=("short", "long_mix"), required=True)
    register.add_argument("--title", required=True)
    register.add_argument("--description", default="")
    register.add_argument("--tag", action="append", default=[])
    register.add_argument("--theme", default=None)
    upload = commands.add_parser("youtube-upload-next", help="upload one video as private")
    upload.add_argument("--confirm-private", action="store_true", required=True)
    render = commands.add_parser("short-render", help="render a five-scene vertical Short")
    render.add_argument("--image", action="append", type=Path, required=True)
    render.add_argument("--audio", action="append", type=Path, required=True)
    render.add_argument("--label", action="append", required=True)
    render.add_argument("--audio-start", action="append", type=float, default=[])
    render.add_argument("--output", type=Path, required=True)
    render.add_argument("--title", required=True)
    render.add_argument("--description", default="")
    render.add_argument("--tag", action="append", default=[])
    render.add_argument("--theme", default=None)
    render.add_argument("--register", action="store_true")
    commands.add_parser("youtube-collect", help="collect YouTube statistics and Analytics")
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
    if args.command == "youtube-auth":
        credentials = authorize(paths, config, open_browser=not args.no_browser)
        print(json.dumps(authorization_summary(credentials), indent=2))
        return
    if args.command == "youtube-status":
        status = connection_status(paths, config)
        print(json.dumps(status.to_dict(), indent=2, ensure_ascii=False))
        raise SystemExit(0 if status.authorized else 1)
    if args.command == "video-register":
        video_id = register_video(
            repository,
            args.file,
            kind=args.kind,
            title=args.title,
            description=args.description,
            tags=args.tag,
            theme=args.theme,
            privacy_status="private",
        )
        print(video_id)
        return
    if args.command == "youtube-upload-next":
        if not args.confirm_private:
            raise SystemExit("--confirm-private is required")
        result = upload_next(paths, config, repository)
        print(json.dumps({"uploaded": result}, indent=2))
        return
    if args.command == "short-render":
        if not (len(args.image) == len(args.audio) == len(args.label) == 5):
            raise SystemExit("Exactly five --image, --audio, and --label arguments are required")
        starts = args.audio_start or [0.0] * 5
        if len(starts) != 5:
            raise SystemExit("Provide either zero or five --audio-start arguments")
        scenes = [
            ShortScene(image=image, audio=audio, label=label, audio_start_sec=start)
            for image, audio, label, start in zip(
                args.image, args.audio, args.label, starts, strict=True
            )
        ]
        probe = render_short(paths, scenes, args.output)
        video_id = None
        if args.register:
            video_id = register_video(
                repository,
                args.output,
                kind="short",
                title=args.title,
                description=args.description,
                tags=args.tag,
                theme=args.theme,
                privacy_status="private",
            )
        print(
            json.dumps(
                {"output": str(args.output.resolve()), "probe": probe.__dict__, "video_id": video_id},
                indent=2,
            )
        )
        return
    if args.command == "youtube-collect":
        result = collect_youtube_analytics(paths, config, repository)
        print(json.dumps(result, indent=2))
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
