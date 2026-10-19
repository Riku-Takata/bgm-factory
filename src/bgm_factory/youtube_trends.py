from __future__ import annotations

import json
import logging
import math
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from googleapiclient.discovery import build

from .config import AppConfig, load_yaml
from .db import Repository
from .paths import ServerPaths
from .youtube_auth import connection_status, load_credentials

logger = logging.getLogger(__name__)


THEME_SIGNALS: dict[str, tuple[str, ...]] = {
    "summer_drive": (
        "drive bgm",
        "driving music",
        "summer drive",
        "coastal drive",
        "ドライブ bgm",
        "夏 bgm",
        "海 bgm",
        "爽やか bgm",
    ),
    "night_drive": (
        "night drive",
        "neon city",
        "midnight music",
        "night bgm",
        "夜 bgm",
        "深夜 bgm",
        "ネオン",
        "雨 bgm",
    ),
    "chill": (
        "chill bgm",
        "relaxing music",
        "リラックス bgm",
        "lofi",
    ),
    "focus_study": (
        "study bgm",
        "focus music",
        "作業用 bgm",
        "勉強 bgm",
        "集中 bgm",
        "productivity music",
    ),
    "morning_fresh": (
        "morning bgm",
        "morning music",
        "朝 bgm",
        "爽やか bgm",
        "wake up music",
    ),
    "rain_cafe": (
        "rain bgm",
        "rainy cafe",
        "cafe bgm",
        "雨 bgm",
        "カフェ bgm",
        "coffee shop music",
    ),
    "ambient_sleep": (
        "ambient music",
        "sleep music",
        "睡眠 bgm",
        "癒し bgm",
        "meditation music",
    ),
    "workout_upbeat": (
        "workout music",
        "training bgm",
        "gym music",
        "運動 bgm",
        "筋トレ bgm",
        "upbeat bgm",
    ),
}

SEARCH_QUERIES: tuple[tuple[str, str], ...] = (
    ("summer_drive", "ドライブ BGM Shorts"),
    ("night_drive", "Night Drive BGM Shorts"),
    ("chill", "Chill BGM Shorts"),
    ("focus_study", "作業用 BGM Shorts"),
    ("morning_fresh", "朝 爽やか BGM Shorts"),
    ("rain_cafe", "雨 カフェ BGM Shorts"),
    ("ambient_sleep", "睡眠 Ambient BGM Shorts"),
    ("workout_upbeat", "Workout BGM Shorts"),
)


@dataclass(frozen=True)
class TrendDecision:
    slot: int
    theme: str
    total_score: float
    source: str
    reason: dict[str, Any]


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def blocked_reason(title: str, blocked_terms: list[str]) -> str | None:
    normalized = normalize_text(title)
    for term in blocked_terms:
        normalized_term = normalize_text(term)
        if normalized_term and normalized_term in normalized:
            return f"blocked_term:{term}"
    return None


def classify_theme(text: str, hinted_theme: str | None = None) -> dict[str, int]:
    normalized = normalize_text(text)
    scores = {theme: 0 for theme in THEME_SIGNALS}
    for theme, signals in THEME_SIGNALS.items():
        scores[theme] = sum(1 for signal in signals if normalize_text(signal) in normalized)
    if hinted_theme in scores:
        scores[hinted_theme] += 2
    return scores


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def velocity_score(item: dict[str, Any], now: datetime) -> float:
    age_hours = max(1.0, (now - _parse_datetime(str(item["published_at"]))).total_seconds() / 3600)
    views_per_hour = max(0.0, float(item.get("view_count", 0)) / age_hours)
    return math.log1p(views_per_hour)


def _video_rows(
    response: dict[str, Any],
    *,
    source: str,
    query: str | None,
    hinted_theme: str | None,
    blocked_terms: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in response.get("items", []):
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        title = str(snippet.get("title") or "")
        reason = blocked_reason(title, blocked_terms)
        rows.append(
            {
                "source": source,
                "query": query,
                "hinted_theme": hinted_theme,
                "youtube_video_id": str(item.get("id") or ""),
                "title": title,
                "channel_title": str(snippet.get("channelTitle") or ""),
                "published_at": str(snippet.get("publishedAt") or datetime.now(UTC).isoformat()),
                "view_count": int(statistics.get("viewCount") or 0),
                "like_count": int(statistics.get("likeCount") or 0),
                "comment_count": int(statistics.get("commentCount") or 0),
                "duration_iso": str(item.get("contentDetails", {}).get("duration") or ""),
                "safe": reason is None,
                "blocked_reason": reason,
            }
        )
    return [row for row in rows if row["youtube_video_id"]]


def collect_trend_snapshots(
    paths: ServerPaths,
    config: AppConfig,
    repository: Repository,
    *,
    run_date: date | None = None,
    youtube: Any | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    run_date = run_date or datetime.now(config.timezone).date()
    now = now or datetime.now(UTC)
    if youtube is None:
        status = connection_status(paths, config)
        if not status.authorized:
            raise RuntimeError(f"YouTube connection check failed: {status.error}")
        youtube = build(
            "youtube", "v3", credentials=load_credentials(paths, config), cache_discovery=False
        )

    snapshots = _video_rows(
        youtube.videos()
        .list(
            part="snippet,statistics,contentDetails",
            chart="mostPopular",
            regionCode=config.youtube.region,
            videoCategoryId=str(config.youtube.category_id),
            maxResults=config.trends.popular_results,
        )
        .execute(),
        source="most_popular",
        query=None,
        hinted_theme=None,
        blocked_terms=config.trends.blocked_terms,
    )

    published_after = (now - timedelta(days=config.trends.lookback_days)).isoformat().replace(
        "+00:00", "Z"
    )
    for hinted_theme, query in SEARCH_QUERIES:
        response = (
            youtube.search()
            .list(
                part="id",
                q=query,
                type="video",
                order="viewCount",
                publishedAfter=published_after,
                regionCode=config.youtube.region,
                relevanceLanguage="ja",
                videoDuration="short",
                maxResults=config.trends.max_results_per_query,
            )
            .execute()
        )
        ids = [str(item.get("id", {}).get("videoId") or "") for item in response.get("items", [])]
        ids = [video_id for video_id in ids if video_id]
        if not ids:
            continue
        details = (
            youtube.videos()
            .list(part="snippet,statistics,contentDetails", id=",".join(ids))
            .execute()
        )
        snapshots.extend(
            _video_rows(
                details,
                source="search",
                query=query,
                hinted_theme=hinted_theme,
                blocked_terms=config.trends.blocked_terms,
            )
        )
    repository.replace_trend_snapshots(run_date, snapshots)
    return snapshots


def _normalized(values: dict[str, float], keys: list[str]) -> dict[str, float]:
    selected = {key: max(0.0, float(values.get(key, 0))) for key in keys}
    maximum = max(selected.values(), default=0.0)
    if maximum <= 0:
        return {key: 0.0 for key in keys}
    return {key: value / maximum for key, value in selected.items()}


def _time_score(theme: str, hour: int) -> float:
    if hour < 10:
        return {
            "morning_fresh": 1.0,
            "focus_study": 0.90,
            "summer_drive": 0.85,
            "chill": 0.70,
            "night_drive": 0.15,
            "ambient_sleep": 0.35,
        }.get(theme, 0.55)
    if hour < 18:
        return {
            "summer_drive": 1.0,
            "focus_study": 0.95,
            "workout_upbeat": 0.90,
            "morning_fresh": 0.70,
            "chill": 0.65,
            "night_drive": 0.35,
        }.get(theme, 0.55)
    return {
        "night_drive": 1.0,
        "ambient_sleep": 0.90,
        "rain_cafe": 0.85,
        "chill": 0.80,
        "summer_drive": 0.40,
        "workout_upbeat": 0.45,
    }.get(theme, 0.55)


def decide_daily_themes(
    paths: ServerPaths,
    config: AppConfig,
    repository: Repository,
    *,
    run_date: date,
    force_fallback: bool = False,
) -> list[TrendDecision]:
    themes = list(load_yaml(paths, "themes.yaml")) or [config.generation.default_theme]
    snapshots = (
        [] if force_fallback else repository.trend_snapshots(run_date, safe_only=True)
    )
    external_raw = {theme: 0.0 for theme in themes}
    freshness_raw = {theme: 0.0 for theme in themes}
    now = datetime.now(UTC)
    evidence: dict[str, list[dict[str, Any]]] = {theme: [] for theme in themes}
    for item in snapshots:
        matches = classify_theme(str(item["title"]), item.get("hinted_theme"))
        velocity = velocity_score(item, now)
        for theme, matches_count in matches.items():
            if theme not in external_raw or matches_count <= 0:
                continue
            contribution = velocity * matches_count
            external_raw[theme] += contribution
            freshness_raw[theme] += 1 / max(
                1.0, (now - _parse_datetime(str(item["published_at"]))).total_seconds() / 86400
            )
            evidence[theme].append(
                {
                    "video_id": item["youtube_video_id"],
                    "title": item["title"],
                    "velocity": round(velocity, 4),
                    "matches": matches_count,
                }
            )

    performance = repository.theme_performance(
        run_date - timedelta(days=30), config.youtube.expected_channel_id
    )
    channel_raw = {
        theme: (
            float(performance.get(theme, {}).get("average_view_percentage", 0))
            + math.log1p(float(performance.get(theme, {}).get("engaged_views", 0))) * 10
            + float(performance.get(theme, {}).get("subscribers_gained", 0)) * 20
        )
        for theme in themes
    }
    external = _normalized(external_raw, themes)
    channel = _normalized(channel_raw, themes)
    freshness = _normalized(freshness_raw, themes)
    weights = config.trends.normalized_weights()
    candidates: list[dict[str, Any]] = []
    for theme in themes:
        base = weights[0] * external[theme] + weights[1] * channel[theme] + weights[3] * freshness[theme]
        candidates.append(
            {
                "theme": theme,
                "external_score": external[theme],
                "channel_score": channel[theme],
                "freshness_score": freshness[theme],
                "total_score": base,
                "evidence_json": json.dumps(evidence[theme][:10], ensure_ascii=False),
            }
        )
    repository.replace_trend_candidates(run_date, candidates)

    source = "youtube_trends" if snapshots else "fallback_rotation"
    decisions: list[TrendDecision] = []
    used: set[str] = set()
    production_times = config.schedule.parsed_production_times()
    for slot, (hour, _) in enumerate(production_times):
        available = [candidate for candidate in candidates if candidate["theme"] not in used]
        if not available:
            available = candidates
        ranked = []
        for candidate in available:
            theme = str(candidate["theme"])
            total = float(candidate["total_score"]) + weights[2] * _time_score(theme, hour)
            ranked.append((total, theme, candidate))
        if source == "fallback_rotation":
            theme = themes[(run_date.toordinal() + slot) % len(themes)]
            selected = next(candidate for candidate in candidates if candidate["theme"] == theme)
            total = float(selected["total_score"])
        else:
            total, theme, selected = max(ranked, key=lambda row: (row[0], row[1]))
        used.add(theme)
        decisions.append(
            TrendDecision(
                slot=slot,
                theme=theme,
                total_score=round(total, 6),
                source=source,
                reason={
                    "external": selected["external_score"],
                    "channel": selected["channel_score"],
                    "freshness": selected["freshness_score"],
                    "time": _time_score(theme, hour),
                    "scheduled_hour": hour,
                },
            )
        )
    repository.replace_daily_theme_decisions(
        run_date,
        [
            {
                "slot": decision.slot,
                "theme": decision.theme,
                "total_score": decision.total_score,
                "source": decision.source,
                "reason_json": json.dumps(decision.reason, ensure_ascii=False),
            }
            for decision in decisions
        ],
    )
    return decisions


def collect_and_decide_daily_themes(
    paths: ServerPaths,
    config: AppConfig,
    repository: Repository,
    *,
    run_date: date | None = None,
) -> list[TrendDecision]:
    run_date = run_date or datetime.now(config.timezone).date()
    if config.trends.enabled:
        collect_trend_snapshots(paths, config, repository, run_date=run_date)
    return decide_daily_themes(
        paths,
        config,
        repository,
        run_date=run_date,
        force_fallback=not config.trends.enabled,
    )


def decision_payload(decisions: list[TrendDecision]) -> list[dict[str, Any]]:
    return [asdict(decision) for decision in decisions]
