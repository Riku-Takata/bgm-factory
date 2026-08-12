from __future__ import annotations

import hashlib
import json
import mimetypes
import random
import time
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .config import AppConfig
from .db import Repository, VideoRecord
from .paths import ServerPaths
from .youtube_auth import connection_status, load_credentials

RETRIABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def sha256_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def register_video(
    repository: Repository,
    file_path: Path,
    *,
    kind: str,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    theme: str | None = None,
    privacy_status: str = "private",
) -> str:
    resolved = file_path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Video file not found: {resolved}")
    if resolved.suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm"}:
        raise ValueError(f"Unsupported video file: {resolved.suffix}")
    if kind not in {"short", "long_mix"}:
        raise ValueError("kind must be 'short' or 'long_mix'")
    return repository.register_video(
        {
            "kind": kind,
            "title": title,
            "description": description,
            "tags_json": json.dumps(tags or [], ensure_ascii=False),
            "theme": theme,
            "output_file": str(resolved),
            "content_hash": sha256_file(resolved),
            "privacy_status": privacy_status,
        }
    )


def upload_video(
    paths: ServerPaths,
    config: AppConfig,
    repository: Repository,
    video: VideoRecord,
) -> str:
    status = connection_status(paths, config)
    if not status.authorized:
        raise RuntimeError(f"YouTube connection check failed: {status.error}")
    if config.youtube.expected_channel_id != status.channel_id:
        raise RuntimeError("Authorized YouTube channel does not match the configured channel")
    if video.privacy_status != "private" and not config.app.auto_publish:
        raise RuntimeError("Only private uploads are allowed while auto_publish is disabled")
    file_path = Path(video.output_file)
    if not file_path.is_file():
        raise FileNotFoundError(f"Video file not found: {file_path}")
    if sha256_file(file_path) != video.content_hash:
        raise RuntimeError("Video content changed after registration; refusing upload")
    if not repository.begin_video_upload(video.id):
        raise RuntimeError("Video is no longer eligible for upload")

    credentials = load_credentials(paths, config)
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    tags = json.loads(video.tags_json)
    body = {
        "snippet": {
            "title": video.title,
            "description": video.description,
            "tags": tags,
            "categoryId": str(config.youtube.category_id),
        },
        "status": {
            "privacyStatus": video.privacy_status,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": config.youtube.contains_synthetic_media,
        },
    }
    media_type = mimetypes.guess_type(file_path.name)[0] or "video/*"
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        notifySubscribers=False,
        media_body=MediaFileUpload(
            str(file_path), mimetype=media_type, chunksize=8 * 1024 * 1024, resumable=True
        ),
    )
    response = None
    retries = 0
    try:
        while response is None:
            try:
                _, response = request.next_chunk()
            except HttpError as exc:
                if exc.resp.status not in RETRIABLE_STATUS_CODES or retries >= 5:
                    raise
                retries += 1
                time.sleep(random.uniform(0, min(60, 2**retries)))
        youtube_video_id = response.get("id")
        if not youtube_video_id:
            raise RuntimeError("YouTube upload returned no video ID")
        repository.finish_video_upload(video.id, youtube_video_id)
        return str(youtube_video_id)
    except Exception as exc:
        repository.mark_video_upload_uncertain(video.id, str(exc))
        raise


def upload_next(
    paths: ServerPaths, config: AppConfig, repository: Repository
) -> tuple[str, str] | None:
    video = repository.next_video_for_upload()
    if video is None:
        return None
    return video.id, upload_video(paths, config, repository, video)
