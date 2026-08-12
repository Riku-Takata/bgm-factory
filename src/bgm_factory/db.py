from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class GenerationJob:
    id: str
    theme: str
    prompt: str
    requested_count: int
    completed_count: int
    accepted_count: int
    state: str
    error_message: str | None


@dataclass(frozen=True)
class VideoRecord:
    id: str
    kind: str
    title: str
    description: str
    tags_json: str
    theme: str | None
    output_file: str
    content_hash: str
    upload_state: str
    privacy_status: str
    youtube_video_id: str | None
    error_message: str | None


SCHEMA = """
CREATE TABLE IF NOT EXISTS bgm_assets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    theme TEXT NOT NULL,
    prompt TEXT NOT NULL,
    model TEXT NOT NULL,
    seed INTEGER,
    bpm REAL,
    musical_key TEXT,
    duration_sec REAL NOT NULL,
    master_file TEXT NOT NULL,
    hook_file TEXT,
    hook_start REAL,
    hook_end REAL,
    loop_start REAL,
    loop_end REAL,
    loop_crossfade_ms INTEGER,
    quality_score REAL,
    hook_score REAL,
    loop_score REAL,
    final_score REAL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    accepted_at TEXT
);

CREATE TABLE IF NOT EXISTS generation_jobs (
    id TEXT PRIMARY KEY,
    theme TEXT NOT NULL,
    prompt TEXT NOT NULL,
    requested_count INTEGER NOT NULL,
    completed_count INTEGER NOT NULL DEFAULT 0,
    accepted_count INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL,
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_generation_jobs_queue
ON generation_jobs(state, created_at);

CREATE TABLE IF NOT EXISTS schedule_runs (
    schedule_name TEXT NOT NULL,
    run_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(schedule_name, run_date)
);

CREATE TABLE IF NOT EXISTS counters (
    name TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS youtube_videos (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    theme TEXT,
    output_file TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    upload_state TEXT NOT NULL DEFAULT 'pending',
    privacy_status TEXT NOT NULL DEFAULT 'private',
    youtube_video_id TEXT UNIQUE,
    upload_attempted_at TEXT,
    uploaded_at TEXT,
    published_at TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_youtube_videos_upload_queue
ON youtube_videos(upload_state, created_at);

CREATE TABLE IF NOT EXISTS youtube_video_snapshots (
    youtube_video_id TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    view_count INTEGER NOT NULL DEFAULT 0,
    like_count INTEGER NOT NULL DEFAULT 0,
    comment_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(youtube_video_id, collected_at)
);

CREATE TABLE IF NOT EXISTS youtube_metrics_daily (
    youtube_video_id TEXT NOT NULL,
    metric_date TEXT NOT NULL,
    views INTEGER NOT NULL DEFAULT 0,
    engaged_views INTEGER NOT NULL DEFAULT 0,
    estimated_minutes_watched REAL NOT NULL DEFAULT 0,
    average_view_duration REAL NOT NULL DEFAULT 0,
    average_view_percentage REAL NOT NULL DEFAULT 0,
    likes INTEGER NOT NULL DEFAULT 0,
    comments INTEGER NOT NULL DEFAULT 0,
    shares INTEGER NOT NULL DEFAULT 0,
    subscribers_gained INTEGER NOT NULL DEFAULT 0,
    collected_at TEXT NOT NULL,
    PRIMARY KEY(youtube_video_id, metric_date)
);

CREATE TABLE IF NOT EXISTS pexels_assets (
    id TEXT PRIMARY KEY,
    theme TEXT NOT NULL,
    search_query TEXT NOT NULL,
    pexels_video_id INTEGER NOT NULL UNIQUE,
    pexels_file_id INTEGER NOT NULL,
    local_file TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    duration_sec REAL NOT NULL,
    fps REAL,
    photographer TEXT NOT NULL,
    photographer_url TEXT NOT NULL,
    source_url TEXT NOT NULL,
    file_url TEXT NOT NULL,
    license_name TEXT NOT NULL,
    license_url TEXT NOT NULL,
    attribution_text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    use_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_pexels_assets_theme
ON pexels_assets(theme, use_count, created_at);
"""


class Repository:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def migrate(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def recover_interrupted_jobs(self) -> int:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE generation_jobs
                SET state = 'queued', updated_at = ?,
                    error_message = 'Recovered after worker restart'
                WHERE state IN ('running', 'analyzing')
                """,
                (now,),
            )
            return cursor.rowcount

    def enqueue_job(self, theme: str, prompt: str, requested_count: int) -> str:
        job_id = f"job_{uuid.uuid4().hex}"
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_jobs (
                    id, theme, prompt, requested_count, completed_count,
                    accepted_count, state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 0, 0, 'queued', ?, ?)
                """,
                (job_id, theme, prompt, requested_count, now, now),
            )
        return job_id

    def enqueue_scheduled_job(
        self, run_date: date, theme: str, prompt: str, requested_count: int
    ) -> str | None:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO schedule_runs(schedule_name, run_date, created_at)
                VALUES ('daily_generation', ?, ?)
                """,
                (run_date.isoformat(), utc_now()),
            )
            if cursor.rowcount == 0:
                return None
            job_id = f"job_{uuid.uuid4().hex}"
            now = utc_now()
            connection.execute(
                """
                INSERT INTO generation_jobs (
                    id, theme, prompt, requested_count, completed_count,
                    accepted_count, state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 0, 0, 'queued', ?, ?)
                """,
                (job_id, theme, prompt, requested_count, now, now),
            )
            return job_id

    def acquire_job(self) -> GenerationJob | None:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM generation_jobs
                WHERE state IN ('queued', 'waiting_gpu')
                ORDER BY created_at
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            now = utc_now()
            connection.execute(
                """
                UPDATE generation_jobs
                SET state = 'running', started_at = COALESCE(started_at, ?),
                    updated_at = ?, error_message = NULL
                WHERE id = ?
                """,
                (now, now, row["id"]),
            )
            data = dict(row)
            data["state"] = "running"
            return GenerationJob(**{key: data[key] for key in GenerationJob.__dataclass_fields__})

    def peek_job(self) -> GenerationJob | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM generation_jobs
                WHERE state IN ('queued', 'waiting_gpu')
                ORDER BY created_at
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            data = dict(row)
            return GenerationJob(**{key: data[key] for key in GenerationJob.__dataclass_fields__})

    def set_job_state(self, job_id: str, state: str, error: str | None = None) -> None:
        completed_at = utc_now() if state in {"completed", "failed", "cancelled"} else None
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE generation_jobs
                SET state = ?, error_message = ?, updated_at = ?,
                    completed_at = COALESCE(?, completed_at)
                WHERE id = ?
                """,
                (state, error, utc_now(), completed_at, job_id),
            )

    def record_candidate(self, job_id: str, accepted: bool) -> tuple[int, int]:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE generation_jobs
                SET completed_count = completed_count + 1,
                    accepted_count = accepted_count + ?, updated_at = ?
                WHERE id = ?
                """,
                (1 if accepted else 0, utc_now(), job_id),
            )
            row = connection.execute(
                "SELECT completed_count, accepted_count FROM generation_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            return int(row["completed_count"]), int(row["accepted_count"])

    def allocate_asset_id(self) -> str:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR IGNORE INTO counters(name, value) VALUES ('bgm_asset', 0)"
            )
            connection.execute("UPDATE counters SET value = value + 1 WHERE name = 'bgm_asset'")
            value = connection.execute(
                "SELECT value FROM counters WHERE name = 'bgm_asset'"
            ).fetchone()[0]
            return f"bgm_{int(value):06d}"

    def asset_name_exists(self, name: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM bgm_assets WHERE name = ? LIMIT 1", (name,)
            ).fetchone()
            return row is not None

    def insert_asset(self, values: dict[str, Any]) -> None:
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        with self.connect() as connection:
            connection.execute(
                f"INSERT INTO bgm_assets ({columns}) VALUES ({placeholders})",
                tuple(values.values()),
            )

    def bgm_assets(self, theme: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            if theme:
                rows = connection.execute(
                    """
                    SELECT * FROM bgm_assets WHERE theme = ? AND status = 'accepted'
                    ORDER BY created_at DESC
                    """,
                    (theme,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM bgm_assets WHERE status = 'accepted'
                    ORDER BY created_at DESC
                    """
                ).fetchall()
            return [dict(row) for row in rows]

    def schedule_run_exists(self, schedule_name: str, run_date: date) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM schedule_runs WHERE schedule_name = ? AND run_date = ?",
                (schedule_name, run_date.isoformat()),
            ).fetchone()
            return row is not None

    def record_schedule_run(self, schedule_name: str, run_date: date) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO schedule_runs(schedule_name, run_date, created_at)
                VALUES (?, ?, ?)
                """,
                (schedule_name, run_date.isoformat(), utc_now()),
            )
            return cursor.rowcount == 1

    def queue_stats(self) -> dict[str, int]:
        stats = {state: 0 for state in ("queued", "waiting_gpu", "running", "completed", "failed")}
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT state, COUNT(*) AS count FROM generation_jobs GROUP BY state"
            ).fetchall()
            for row in rows:
                stats[str(row["state"])] = int(row["count"])
            stats["assets"] = int(
                connection.execute("SELECT COUNT(*) FROM bgm_assets").fetchone()[0]
            )
        return stats

    def recent_jobs(self, limit: int = 10) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM generation_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    def upsert_pexels_asset(self, values: dict[str, Any]) -> str:
        asset_id = values.get("id") or f"pexels_{values['pexels_video_id']}"
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO pexels_assets (
                    id, theme, search_query, pexels_video_id, pexels_file_id,
                    local_file, content_hash, width, height, duration_sec, fps,
                    photographer, photographer_url, source_url, file_url,
                    license_name, license_url, attribution_text, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pexels_video_id) DO UPDATE SET
                    local_file = excluded.local_file,
                    content_hash = excluded.content_hash,
                    pexels_file_id = excluded.pexels_file_id,
                    width = excluded.width,
                    height = excluded.height,
                    fps = excluded.fps
                """,
                (
                    asset_id,
                    values["theme"],
                    values["search_query"],
                    values["pexels_video_id"],
                    values["pexels_file_id"],
                    values["local_file"],
                    values["content_hash"],
                    values["width"],
                    values["height"],
                    values["duration_sec"],
                    values.get("fps"),
                    values["photographer"],
                    values["photographer_url"],
                    values["source_url"],
                    values["file_url"],
                    values["license_name"],
                    values["license_url"],
                    values["attribution_text"],
                    values.get("created_at", utc_now()),
                ),
            )
        return str(asset_id)

    def pexels_asset_ids(self) -> set[int]:
        with self.connect() as connection:
            rows = connection.execute("SELECT pexels_video_id FROM pexels_assets").fetchall()
            return {int(row["pexels_video_id"]) for row in rows}

    def pexels_assets(self, theme: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            if theme:
                rows = connection.execute(
                    """
                    SELECT * FROM pexels_assets WHERE theme = ?
                    ORDER BY use_count, created_at
                    """,
                    (theme,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM pexels_assets ORDER BY theme, use_count, created_at"
                ).fetchall()
            return [dict(row) for row in rows]

    def mark_pexels_assets_used(self, asset_ids: list[str]) -> None:
        if not asset_ids:
            return
        placeholders = ", ".join("?" for _ in asset_ids)
        with self.connect() as connection:
            connection.execute(
                f"""
                UPDATE pexels_assets
                SET use_count = use_count + 1, last_used_at = ?
                WHERE id IN ({placeholders})
                """,
                (utc_now(), *asset_ids),
            )

    def register_video(self, values: dict[str, Any]) -> str:
        now = utc_now()
        video_id = values.get("id") or f"video_{uuid.uuid4().hex}"
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM youtube_videos WHERE content_hash = ?",
                (values["content_hash"],),
            ).fetchone()
            if existing:
                return str(existing["id"])
            connection.execute(
                """
                INSERT INTO youtube_videos (
                    id, kind, title, description, tags_json, theme, output_file,
                    content_hash, upload_state, privacy_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    video_id,
                    values["kind"],
                    values["title"],
                    values.get("description", ""),
                    values.get("tags_json", "[]"),
                    values.get("theme"),
                    values["output_file"],
                    values["content_hash"],
                    values.get("privacy_status", "private"),
                    now,
                    now,
                ),
            )
        return str(video_id)

    def get_video(self, video_id: str) -> VideoRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM youtube_videos WHERE id = ?", (video_id,)
            ).fetchone()
        return self._video_record(row)

    def next_video_for_upload(self) -> VideoRecord | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM youtube_videos
                WHERE youtube_video_id IS NULL AND upload_state = 'pending'
                ORDER BY created_at
                LIMIT 1
                """
            ).fetchone()
        return self._video_record(row)

    def begin_video_upload(self, video_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE youtube_videos
                SET upload_state = 'uploading', upload_attempted_at = ?,
                    error_message = NULL, updated_at = ?
                WHERE id = ? AND youtube_video_id IS NULL AND upload_state = 'pending'
                """,
                (utc_now(), utc_now(), video_id),
            )
            return cursor.rowcount == 1

    def finish_video_upload(self, video_id: str, youtube_video_id: str) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE youtube_videos
                SET upload_state = 'completed', youtube_video_id = ?, uploaded_at = ?,
                    error_message = NULL, updated_at = ?
                WHERE id = ?
                """,
                (youtube_video_id, now, now, video_id),
            )

    def mark_video_upload_uncertain(self, video_id: str, error: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE youtube_videos
                SET upload_state = 'uncertain', error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (error, utc_now(), video_id),
            )

    def uploaded_videos(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM youtube_videos
                WHERE youtube_video_id IS NOT NULL
                ORDER BY uploaded_at DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def record_video_snapshot(
        self,
        youtube_video_id: str,
        view_count: int,
        like_count: int,
        comment_count: int,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO youtube_video_snapshots (
                    youtube_video_id, collected_at, view_count, like_count, comment_count
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (youtube_video_id, utc_now(), view_count, like_count, comment_count),
            )

    def upsert_daily_metric(self, values: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO youtube_metrics_daily (
                    youtube_video_id, metric_date, views, engaged_views,
                    estimated_minutes_watched, average_view_duration,
                    average_view_percentage, likes, comments, shares,
                    subscribers_gained, collected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(youtube_video_id, metric_date) DO UPDATE SET
                    views = excluded.views,
                    engaged_views = excluded.engaged_views,
                    estimated_minutes_watched = excluded.estimated_minutes_watched,
                    average_view_duration = excluded.average_view_duration,
                    average_view_percentage = excluded.average_view_percentage,
                    likes = excluded.likes,
                    comments = excluded.comments,
                    shares = excluded.shares,
                    subscribers_gained = excluded.subscribers_gained,
                    collected_at = excluded.collected_at
                """,
                (
                    values["youtube_video_id"],
                    values["metric_date"],
                    values.get("views", 0),
                    values.get("engaged_views", 0),
                    values.get("estimated_minutes_watched", 0),
                    values.get("average_view_duration", 0),
                    values.get("average_view_percentage", 0),
                    values.get("likes", 0),
                    values.get("comments", 0),
                    values.get("shares", 0),
                    values.get("subscribers_gained", 0),
                    utc_now(),
                ),
            )

    def dashboard_data(self) -> dict[str, Any]:
        with self.connect() as connection:
            totals = connection.execute(
                """
                SELECT
                    COALESCE(SUM(latest.view_count), 0) AS views,
                    COALESCE(SUM(latest.like_count), 0) AS likes,
                    COALESCE(SUM(latest.comment_count), 0) AS comments
                FROM youtube_videos AS videos
                LEFT JOIN youtube_video_snapshots AS latest
                    ON latest.youtube_video_id = videos.youtube_video_id
                   AND latest.collected_at = (
                       SELECT MAX(s.collected_at)
                       FROM youtube_video_snapshots AS s
                       WHERE s.youtube_video_id = videos.youtube_video_id
                   )
                WHERE videos.youtube_video_id IS NOT NULL
                """
            ).fetchone()
            daily = connection.execute(
                """
                SELECT metric_date, SUM(views) AS views,
                       SUM(engaged_views) AS engaged_views,
                       SUM(estimated_minutes_watched) AS watched_minutes
                FROM youtube_metrics_daily
                GROUP BY metric_date
                ORDER BY metric_date
                """
            ).fetchall()
            videos = connection.execute(
                """
                SELECT v.id, v.title, v.kind, v.youtube_video_id, v.upload_state,
                       v.uploaded_at, COALESCE(s.view_count, 0) AS views,
                       COALESCE(s.like_count, 0) AS likes,
                       COALESCE(s.comment_count, 0) AS comments
                FROM youtube_videos AS v
                LEFT JOIN youtube_video_snapshots AS s
                    ON s.youtube_video_id = v.youtube_video_id
                   AND s.collected_at = (
                       SELECT MAX(s2.collected_at)
                       FROM youtube_video_snapshots AS s2
                       WHERE s2.youtube_video_id = v.youtube_video_id
                   )
                ORDER BY COALESCE(s.view_count, 0) DESC, v.created_at DESC
                """
            ).fetchall()
            states = connection.execute(
                "SELECT upload_state, COUNT(*) AS count FROM youtube_videos GROUP BY upload_state"
            ).fetchall()
        return {
            "totals": dict(totals),
            "daily": [dict(row) for row in daily],
            "videos": [dict(row) for row in videos],
            "upload_states": {str(row["upload_state"]): int(row["count"]) for row in states},
        }

    @staticmethod
    def _video_record(row: sqlite3.Row | None) -> VideoRecord | None:
        if row is None:
            return None
        data = dict(row)
        return VideoRecord(**{key: data[key] for key in VideoRecord.__dataclass_fields__})
