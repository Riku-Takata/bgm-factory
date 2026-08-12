from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Self
from urllib.parse import urlparse

import httpx

from .config import AppConfig, PexelsSettings, load_yaml
from .db import Repository
from .paths import ServerPaths

API_BASE = "https://api.pexels.com/v1"
LICENSE_NAME = "Pexels License"
LICENSE_URL = "https://www.pexels.com/license/"


@dataclass(frozen=True)
class CachedPexelsAsset:
    id: str
    theme: str
    search_query: str
    pexels_video_id: int
    pexels_file_id: int
    local_file: str
    content_hash: str
    width: int
    height: int
    duration_sec: float
    fps: float | None
    photographer: str
    photographer_url: str
    source_url: str
    file_url: str
    license_name: str
    license_url: str
    attribution_text: str
    created_at: str


class PexelsClient:
    def __init__(
        self,
        settings: PexelsSettings,
        api_key: str,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key.strip() or api_key == "CHANGE_ME":
            raise RuntimeError(f"{settings.api_key_env} is not configured")
        self.settings = settings
        self.client = client or httpx.Client(
            headers={"Authorization": api_key.strip()},
            timeout=settings.request_timeout_sec,
            follow_redirects=True,
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def search_videos(self, query: str, *, per_page: int = 15, page: int = 1) -> list[dict]:
        response = self.client.get(
            f"{API_BASE}/videos/search",
            params={
                "query": query,
                "orientation": "portrait",
                "size": "medium",
                "min_duration": self.settings.min_duration_sec,
                "max_duration": self.settings.max_duration_sec,
                "per_page": min(max(per_page, 1), 80),
                "page": max(page, 1),
            },
        )
        response.raise_for_status()
        return list(response.json().get("videos", []))

    def choose_file(self, video: dict) -> dict | None:
        duration = float(video.get("duration") or 0)
        if not self.settings.min_duration_sec <= duration <= self.settings.max_duration_sec:
            return None
        candidates = []
        for item in video.get("video_files", []):
            width = int(item.get("width") or 0)
            height = int(item.get("height") or 0)
            if item.get("file_type") != "video/mp4" or not _allowed_media_url(item.get("link")):
                continue
            if width < self.settings.min_width or height < self.settings.min_height:
                continue
            if height <= width:
                continue
            candidates.append(item)
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda item: (
                abs((int(item["width"]) / int(item["height"])) - (9 / 16)),
                abs(int(item["width"]) - 1080),
                int(item["width"]) * int(item["height"]),
            ),
        )

    def cache_video(
        self,
        paths: ServerPaths,
        repository: Repository,
        *,
        theme: str,
        query: str,
        video: dict,
    ) -> CachedPexelsAsset | None:
        selected = self.choose_file(video)
        if selected is None:
            return None
        video_id = int(video["id"])
        file_id = int(selected["id"])
        target_dir = paths.data_root / "visual-assets" / "pexels" / theme / str(video_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{file_id}.mp4"
        digest = _download(self.client, selected["link"], target, self.settings.max_download_mb)
        user = video.get("user") or {}
        photographer = str(user.get("name") or "Unknown contributor")
        source_url = str(video.get("url") or "")
        attribution = f"Video by {photographer} on Pexels: {source_url}"
        created_at = datetime.now(UTC).isoformat()
        asset = CachedPexelsAsset(
            id=f"pexels_{video_id}",
            theme=theme,
            search_query=query,
            pexels_video_id=video_id,
            pexels_file_id=file_id,
            local_file=str(target.resolve()),
            content_hash=digest,
            width=int(selected["width"]),
            height=int(selected["height"]),
            duration_sec=float(video.get("duration") or 0),
            fps=float(selected["fps"]) if selected.get("fps") is not None else None,
            photographer=photographer,
            photographer_url=str(user.get("url") or ""),
            source_url=source_url,
            file_url=str(selected["link"]),
            license_name=LICENSE_NAME,
            license_url=LICENSE_URL,
            attribution_text=attribution,
            created_at=created_at,
        )
        values = asdict(asset)
        repository.upsert_pexels_asset(values)
        metadata = values | {"provider": "Pexels", "downloaded_via": "Pexels API"}
        (target_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return asset


def configured_client(config: AppConfig, *, client: httpx.Client | None = None) -> PexelsClient:
    return PexelsClient(
        config.pexels,
        os.environ.get(config.pexels.api_key_env, ""),
        client=client,
    )


def theme_video_queries(paths: ServerPaths, theme: str) -> list[str]:
    themes = load_yaml(paths, "themes.yaml")
    if theme not in themes:
        raise KeyError(f"Unknown theme: {theme}")
    queries = themes[theme].get("video_queries") or []
    if not queries:
        raise ValueError(f"Theme has no video_queries: {theme}")
    return [str(query) for query in queries]


def fetch_theme_assets(
    paths: ServerPaths,
    config: AppConfig,
    repository: Repository,
    *,
    theme: str,
    limit: int = 5,
    per_query: int = 12,
) -> list[CachedPexelsAsset]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    existing = repository.pexels_asset_ids()
    cached: list[CachedPexelsAsset] = []
    with configured_client(config) as pexels:
        for query in theme_video_queries(paths, theme):
            for video in pexels.search_videos(query, per_page=per_query):
                if int(video["id"]) in existing:
                    continue
                asset = pexels.cache_video(
                    paths, repository, theme=theme, query=query, video=video
                )
                if asset is None:
                    continue
                cached.append(asset)
                existing.add(asset.pexels_video_id)
                break
            if len(cached) >= limit:
                break
    return cached


def cached_theme_scenes(repository: Repository, theme: str, *, count: int = 5) -> list[dict]:
    assets = [asset for asset in repository.pexels_assets(theme) if Path(asset["local_file"]).is_file()]
    if len(assets) < count:
        raise RuntimeError(f"Theme {theme} needs {count} cached Pexels videos; found {len(assets)}")
    selected: list[dict] = []
    seen_queries: set[str] = set()
    for asset in assets:
        query = str(asset["search_query"])
        if query in seen_queries:
            continue
        selected.append(asset)
        seen_queries.add(query)
        if len(selected) == count:
            break
    if len(selected) < count:
        raise RuntimeError(f"Theme {theme} needs {count} distinct Pexels scene queries")
    return selected


def pexels_attribution_block(assets: list[dict]) -> str:
    lines = ["Visual credits (Pexels):"]
    lines.extend(str(asset["attribution_text"]) for asset in assets)
    lines.append(f"License: {LICENSE_URL}")
    return "\n".join(lines)


def _allowed_media_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host == "pexels.com" or host.endswith(".pexels.com"))


def _download(client: httpx.Client, url: str, target: Path, max_download_mb: int) -> str:
    if not _allowed_media_url(url):
        raise ValueError("Pexels returned an unsupported media URL")
    maximum = max_download_mb * 1024 * 1024
    temporary = target.with_suffix(target.suffix + ".part")
    digest = hashlib.sha256()
    written = 0
    try:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            length = int(response.headers.get("content-length") or 0)
            if length > maximum:
                raise ValueError(f"Pexels video exceeds {max_download_mb} MB")
            with temporary.open("wb") as handle:
                for chunk in response.iter_bytes(1024 * 1024):
                    written += len(chunk)
                    if written > maximum:
                        raise ValueError(f"Pexels video exceeds {max_download_mb} MB")
                    digest.update(chunk)
                    handle.write(chunk)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return digest.hexdigest()
