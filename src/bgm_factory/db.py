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
