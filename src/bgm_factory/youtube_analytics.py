from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from googleapiclient.discovery import build

from .config import AppConfig
from .db import Repository
from .paths import ServerPaths
from .youtube_auth import connection_status, load_credentials

ANALYTICS_METRICS = (
    "views,engagedViews,estimatedMinutesWatched,averageViewDuration,"
    "averageViewPercentage,likes,comments,shares,subscribersGained"
)


def _integer(value: Any) -> int:
    return int(float(value or 0))


def _number(value: Any) -> float:
    return float(value or 0)


def collect_youtube_analytics(
    paths: ServerPaths, config: AppConfig, repository: Repository
) -> dict[str, int]:
    videos = repository.uploaded_videos()
    if not videos:
        return {"videos": 0, "snapshots": 0, "daily_rows": 0}
    status = connection_status(paths, config)
    if not status.authorized:
        raise RuntimeError(f"YouTube connection check failed: {status.error}")
    credentials = load_credentials(paths, config)
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    analytics = build("youtubeAnalytics", "v2", credentials=credentials, cache_discovery=False)
    video_ids = [str(video["youtube_video_id"]) for video in videos]
    local_video_ids = {
        str(video["youtube_video_id"]): str(video["id"])
        for video in videos
        if video.get("youtube_video_id")
    }

    snapshots = 0
    current_channel_video_ids: list[str] = []
    for offset in range(0, len(video_ids), 50):
        batch = video_ids[offset : offset + 50]
        response = (
            youtube.videos()
            .list(part="snippet,statistics", id=",".join(batch))
            .execute()
        )
        for item in response.get("items", []):
            statistics = item.get("statistics", {})
            snippet = item.get("snippet", {})
            local_video_id = local_video_ids.get(str(item["id"]))
            channel_id = snippet.get("channelId")
            if local_video_id and channel_id:
                repository.set_video_channel(local_video_id, str(channel_id))
            if channel_id == status.channel_id:
                current_channel_video_ids.append(str(item["id"]))
            repository.record_video_snapshot(
                item["id"],
                _integer(statistics.get("viewCount")),
                _integer(statistics.get("likeCount")),
                _integer(statistics.get("commentCount")),
            )
            snapshots += 1

    end_date = datetime.now(UTC).date()
    start_date = end_date - timedelta(days=config.analytics.lookback_days)
    daily_rows = 0
    for offset in range(0, len(current_channel_video_ids), 500):
        batch = current_channel_video_ids[offset : offset + 500]
        response = (
            analytics.reports()
            .query(
                ids="channel==MINE",
                startDate=start_date.isoformat(),
                endDate=end_date.isoformat(),
                metrics=ANALYTICS_METRICS,
                dimensions="day,video",
                filters=f"video=={','.join(batch)}",
                sort="day,video",
            )
            .execute()
        )
        headers = [header["name"] for header in response.get("columnHeaders", [])]
        for row in response.get("rows", []):
            values = dict(zip(headers, row, strict=True))
            repository.upsert_daily_metric(
                {
                    "youtube_video_id": values["video"],
                    "metric_date": values["day"],
                    "views": _integer(values.get("views")),
                    "engaged_views": _integer(values.get("engagedViews")),
                    "estimated_minutes_watched": _number(
                        values.get("estimatedMinutesWatched")
                    ),
                    "average_view_duration": _number(values.get("averageViewDuration")),
                    "average_view_percentage": _number(
                        values.get("averageViewPercentage")
                    ),
                    "likes": _integer(values.get("likes")),
                    "comments": _integer(values.get("comments")),
                    "shares": _integer(values.get("shares")),
                    "subscribers_gained": _integer(values.get("subscribersGained")),
                }
            )
            daily_rows += 1
    return {
        "videos": len(current_channel_video_ids),
        "snapshots": snapshots,
        "daily_rows": daily_rows,
    }
