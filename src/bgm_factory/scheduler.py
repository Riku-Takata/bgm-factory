from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from .config import AppConfig
from .db import Repository
from .paths import ServerPaths
from .production import create_daily_short
from .prompt import build_prompt
from .youtube_analytics import collect_youtube_analytics
from .youtube_trends import collect_and_decide_daily_themes, decide_daily_themes
from .youtube_uploader import upload_next

logger = logging.getLogger(__name__)


def enqueue_daily_generation(
    paths: ServerPaths, config: AppConfig, repository: Repository
) -> list[str]:
    now = datetime.now(config.timezone)
    decisions = repository.daily_theme_decisions(now.date())
    if not decisions:
        decisions = [
            {
                "theme": decision.theme,
            }
            for decision in decide_daily_themes(paths, config, repository, run_date=now.date())
        ]
    themes = list(dict.fromkeys(str(decision["theme"]) for decision in decisions))
    job_ids: list[str] = []
    for index, theme in enumerate(themes):
        prompt, _ = build_prompt(theme, paths, now.date().toordinal() + index)
        job_id = repository.enqueue_scheduled_job(
            now.date(),
            theme,
            prompt,
            config.generation.candidates_per_theme,
            schedule_name=f"daily_generation_{theme}",
        )
        if job_id:
            logger.info("scheduled generation job=%s theme=%s", job_id, theme)
            job_ids.append(job_id)
    return job_ids


def collect_trends_job(
    paths: ServerPaths, config: AppConfig, repository: Repository
) -> None:
    try:
        decisions = collect_and_decide_daily_themes(paths, config, repository)
        logger.info("daily trend themes selected decisions=%s", decisions)
    except Exception:
        logger.exception("daily trend collection failed; applying fallback rotation")
        try:
            decisions = decide_daily_themes(
                paths,
                config,
                repository,
                run_date=datetime.now(config.timezone).date(),
                force_fallback=True,
            )
            logger.info("fallback daily themes selected decisions=%s", decisions)
        except Exception:
            logger.exception("fallback daily theme selection failed")


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
            logger.info("youtube upload completed result=%s", result)
    except Exception:
        logger.exception("youtube upload failed")


def create_daily_short_job(
    paths: ServerPaths, config: AppConfig, repository: Repository, slot: int
) -> None:
    try:
        result = create_daily_short(
            paths,
            config,
            repository,
            run_date=datetime.now(config.timezone).date(),
            slot=slot,
        )
        logger.info("daily Short created result=%s", result)
    except Exception:
        logger.exception("daily Short creation failed")


def create_scheduler(
    paths: ServerPaths, config: AppConfig, repository: Repository
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=config.timezone)
    scheduler.add_job(
        collect_trends_job,
        "cron",
        hour=config.trends.collection_hour,
        minute=config.trends.collection_minute,
        args=(paths, config, repository),
        id="daily_youtube_trends",
        coalesce=True,
        max_instances=1,
    )
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
    for slot, (hour, minute) in enumerate(config.schedule.parsed_production_times()):
        scheduler.add_job(
            create_daily_short_job,
            "cron",
            hour=hour,
            minute=minute,
            args=(paths, config, repository, slot),
            id=f"daily_short_production_{slot:02d}",
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
