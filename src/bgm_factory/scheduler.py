from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from .config import AppConfig, load_yaml
from .db import Repository
from .paths import ServerPaths
from .prompt import build_prompt
from .youtube_analytics import collect_youtube_analytics
from .youtube_uploader import upload_next

logger = logging.getLogger(__name__)


def enqueue_daily_generation(
    paths: ServerPaths, config: AppConfig, repository: Repository
) -> str | None:
    now = datetime.now(config.timezone)
    themes = list(load_yaml(paths, "themes.yaml"))
    theme = themes[now.date().toordinal() % len(themes)] if themes else config.generation.default_theme
    prompt, _ = build_prompt(theme, paths, now.date().toordinal())
    job_id = repository.enqueue_scheduled_job(
        now.date(), theme, prompt, config.generation.candidates_per_theme
    )
    if job_id:
        logger.info("scheduled generation job=%s theme=%s", job_id, theme)
    return job_id


def cleanup_runtime(paths: ServerPaths, config: AppConfig) -> int:
    removed = 0
    policies = (
        (
            paths.data_root / "generated" / "rejected",
            config.storage.rejected_retention_days,
        ),
        (paths.data_root / "temp", 1),
    )
    now = datetime.now(UTC).timestamp()
    for root, retention_days in policies:
        if not root.exists():
            continue
        cutoff = now - timedelta(days=retention_days).total_seconds()
        for file_path in root.rglob("*"):
            if file_path.is_file() and file_path.stat().st_mtime < cutoff:
                file_path.unlink(missing_ok=True)
                removed += 1
        for directory in sorted(
            (path for path in root.rglob("*") if path.is_dir()), reverse=True
        ):
            try:
                directory.rmdir()
            except OSError:
                pass
    logger.info("cleanup removed_files=%s", removed)
    return removed


def collect_analytics_job(
    paths: ServerPaths, config: AppConfig, repository: Repository
) -> None:
    if not config.analytics.enabled:
        return
    try:
        result = collect_youtube_analytics(paths, config, repository)
        logger.info("youtube analytics collected result=%s", result)
    except Exception:
        logger.exception("youtube analytics collection failed")


def upload_next_job(paths: ServerPaths, config: AppConfig, repository: Repository) -> None:
    if not config.app.auto_upload:
        return
    try:
        result = upload_next(paths, config, repository)
        if result:
            logger.info("youtube private upload completed result=%s", result)
    except Exception:
        logger.exception("youtube private upload failed")


def create_scheduler(
    paths: ServerPaths, config: AppConfig, repository: Repository
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=config.timezone)
    scheduler.add_job(
        enqueue_daily_generation,
        "cron",
        hour=config.schedule.generation_hour,
        minute=config.schedule.generation_minute,
        args=(paths, config, repository),
        id="daily_generation",
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        cleanup_runtime,
        "cron",
        hour=config.schedule.cleanup_hour,
        minute=config.schedule.cleanup_minute,
        args=(paths, config),
        id="daily_cleanup",
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        collect_analytics_job,
        "cron",
        hour=config.analytics.collection_hour,
        minute=config.analytics.collection_minute,
        args=(paths, config, repository),
        id="daily_youtube_analytics",
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        upload_next_job,
        "interval",
        minutes=config.youtube.upload_poll_minutes,
        args=(paths, config, repository),
        id="youtube_upload_queue",
        coalesce=True,
        max_instances=1,
    )
    return scheduler
