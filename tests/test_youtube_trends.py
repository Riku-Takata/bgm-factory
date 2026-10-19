from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from bgm_factory.config import AppConfig
from bgm_factory.db import Repository
from bgm_factory.paths import ServerPaths
from bgm_factory.youtube_trends import (
    blocked_reason,
    classify_theme,
    decide_daily_themes,
    velocity_score,
)


def make_paths(tmp_path: Path) -> ServerPaths:
    paths = ServerPaths(
        server_root=tmp_path,
        app_root=tmp_path / "app",
        data_root=tmp_path / "data",
        config_root=tmp_path / "config",
        log_root=tmp_path / "logs",
        ace_step_root=tmp_path / "ace",
    )
    paths.config_root.mkdir(parents=True)
    (paths.config_root / "themes.yaml").write_text(
        "summer_drive: {}\nnight_drive: {}\nchill: {}\n", encoding="utf-8"
    )
    return paths


def test_blocked_terms_are_normalized() -> None:
    assert blocked_reason("ANIME Official Music Video", ["official music video"]) is not None
    assert blocked_reason("爽やかなドライブ BGM", ["official music video"]) is None


def test_theme_classification_uses_safe_signals_and_query_hint() -> None:
    scores = classify_theme("海辺のドライブ BGM", hinted_theme="summer_drive")

    assert scores["summer_drive"] >= 3
    assert scores["night_drive"] == 0


def test_velocity_favors_recent_views() -> None:
    now = datetime(2026, 8, 12, tzinfo=UTC)
    recent = {"published_at": (now - timedelta(hours=2)).isoformat(), "view_count": 1000}
    old = {"published_at": (now - timedelta(hours=20)).isoformat(), "view_count": 1000}

    assert velocity_score(recent, now) > velocity_score(old, now)


def test_decision_falls_back_and_persists_three_slots(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    repository = Repository(paths.data_root / "db" / "factory.sqlite")
    repository.migrate()
    run_date = date(2026, 8, 12)

    decisions = decide_daily_themes(paths, AppConfig(), repository, run_date=run_date)

    assert len(decisions) == 3
    assert all(decision.source == "fallback_rotation" for decision in decisions)
    assert len(repository.daily_theme_decisions(run_date)) == 3


def test_safe_trend_evidence_changes_ranking(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    repository = Repository(paths.data_root / "db" / "factory.sqlite")
    repository.migrate()
    run_date = date.today()  # noqa: DTZ011 - database model stores a calendar date.
    repository.replace_trend_snapshots(
        run_date,
        [
            {
                "source": "search",
                "query": "Night Drive BGM Shorts",
                "hinted_theme": "night_drive",
                "youtube_video_id": "night1",
                "title": "Neon Night Drive BGM",
                "channel_title": "Creator",
                "published_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
                "view_count": 100000,
                "safe": True,
            }
        ],
    )

    decisions = decide_daily_themes(paths, AppConfig(), repository, run_date=run_date)
    candidates = repository.trend_candidates(run_date)

    assert decisions[0].source == "youtube_trends"
    assert candidates[0]["theme"] == "night_drive"
