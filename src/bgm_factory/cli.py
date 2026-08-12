from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from .pexels import cached_theme_scenes, fetch_theme_assets, pexels_attribution_block
from .production import create_daily_short
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
    render.add_argument("--image", action="append", type=Path, default=[])
    render.add_argument("--visual", action="append", type=Path, default=[])
    render.add_argument("--audio", action="append", type=Path, required=True)
    render.add_argument("--label", action="append", required=True)
    render.add_argument("--visual-start", action="append", type=float, default=[])
    render.add_argument("--audio-start", action="append", type=float, default=[])
    render.add_argument("--output", type=Path, required=True)
    render.add_argument("--title", required=True)
    render.add_argument("--description", default="")
    render.add_argument("--tag", action="append", default=[])
    render.add_argument("--theme", default=None)
    render.add_argument("--register", action="store_true")
    pexels_render = commands.add_parser(
        "pexels-short-render", help="render a Short from cached Pexels videos"
    )
    pexels_render.add_argument("--theme", default=None)
    pexels_render.add_argument("--audio", action="append", type=Path, required=True)
    pexels_render.add_argument("--label", action="append", required=True)
    pexels_render.add_argument("--audio-start", action="append", type=float, default=[])
    pexels_render.add_argument("--visual-start", action="append", type=float, default=[])
    pexels_render.add_argument("--output", type=Path, required=True)
    pexels_render.add_argument("--title", required=True)
    pexels_render.add_argument("--description", default="")
    pexels_render.add_argument("--tag", action="append", default=[])
    pexels_render.add_argument("--register", action="store_true")
    pexels_fetch = commands.add_parser(
        "pexels-fetch", help="cache portrait stock videos and their attribution metadata"
    )
    pexels_fetch.add_argument("--theme", default=None)
    pexels_fetch.add_argument("--limit", type=int, default=5)
    pexels_fetch.add_argument("--per-query", type=int, default=12)
    produce = commands.add_parser(
        "produce-daily-short", help="render and register one production Short"
    )
    produce.add_argument("--date", type=date.fromisoformat, default=None)
    produce.add_argument("--theme", default=None)
    produce.add_argument("--slot", type=int, default=0)
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
        visuals = args.visual or args.image
        if args.visual and args.image:
            raise SystemExit("Use --visual or the legacy --image option, not both")
        if not (len(visuals) == len(args.audio) == len(args.label) == 5):
            raise SystemExit("Exactly five --visual, --audio, and --label arguments are required")
        starts = args.audio_start or [0.0] * 5
        visual_starts = args.visual_start or [0.0] * 5
        if len(starts) != 5 or len(visual_starts) != 5:
            raise SystemExit("Provide either zero or five scene start arguments")
        scenes = [
            ShortScene(
                visual=visual,
                audio=audio,
                label=label,
                visual_start_sec=visual_start,
                audio_start_sec=start,
            )
            for visual, audio, label, visual_start, start in zip(
                visuals, args.audio, args.label, visual_starts, starts, strict=True
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
    if args.command == "pexels-short-render":
        theme = args.theme or config.generation.default_theme
        assets = cached_theme_scenes(repository, theme)
        if not (len(args.audio) == len(args.label) == 5):
            raise SystemExit("Exactly five --audio and --label arguments are required")
        starts = args.audio_start or [0.0] * 5
        visual_starts = args.visual_start or [0.0] * 5
        if len(starts) != 5 or len(visual_starts) != 5:
            raise SystemExit("Provide either zero or five scene start arguments")
        scenes = [
            ShortScene(
                visual=Path(asset["local_file"]),
                audio=audio,
                label=label,
                visual_start_sec=visual_start,
                audio_start_sec=audio_start,
            )
            for asset, audio, label, visual_start, audio_start in zip(
                assets, args.audio, args.label, visual_starts, starts, strict=True
            )
        ]
        probe = render_short(paths, scenes, args.output)
        description = args.description.strip()
        credits = pexels_attribution_block(assets)
        description = f"{description}\n\n{credits}" if description else credits
        video_id = None
        if args.register:
            video_id = register_video(
                repository,
                args.output,
                kind="short",
                title=args.title,
                description=description,
                tags=args.tag,
                theme=theme,
                privacy_status="private",
            )
            repository.mark_pexels_assets_used([str(asset["id"]) for asset in assets])
        print(
            json.dumps(
                {
                    "output": str(args.output.resolve()),
                    "probe": probe.__dict__,
                    "video_id": video_id,
                    "pexels_assets": [asset["id"] for asset in assets],
                    "description": description,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if args.command == "pexels-fetch":
        theme = args.theme or config.generation.default_theme
        assets = fetch_theme_assets(
            paths,
            config,
            repository,
            theme=theme,
            limit=args.limit,
            per_query=args.per_query,
        )
        print(
            json.dumps(
                {
                    "theme": theme,
                    "downloaded": len(assets),
                    "assets": [
                        {
                            "id": asset.id,
                            "local_file": asset.local_file,
                            "query": asset.search_query,
                            "attribution": asset.attribution_text,
                        }
                        for asset in assets
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if args.command == "produce-daily-short":
        result = create_daily_short(
            paths,
            config,
            repository,
            run_date=args.date or date.today(),  # noqa: DTZ011 - CLI date uses server local date.
            theme=args.theme,
            slot=args.slot,
        )
        print(
            json.dumps(
                {
                    "video_id": result.video_id,
                    "output": str(result.output_file),
                    "title": result.title,
                    "privacy_status": result.privacy_status,
                    "pexels_assets": result.pexels_asset_ids,
                    "probe": result.probe.__dict__,
                },
                ensure_ascii=False,
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
