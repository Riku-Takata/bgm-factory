import json
from datetime import date
from pathlib import Path

from bgm_factory.config import AppConfig
from bgm_factory.db import Repository
from bgm_factory.paths import ServerPaths
from bgm_factory.production import production_audio_sources, theme_for_date


def test_production_audio_uses_only_eligible_candidates(tmp_path: Path) -> None:
    paths = ServerPaths(
        server_root=tmp_path,
        app_root=tmp_path / "app",
        data_root=tmp_path / "data",
        config_root=tmp_path / "config",
        log_root=tmp_path / "logs",
        ace_step_root=tmp_path / "ace",
    )
    repository = Repository(paths.data_root / "db" / "factory.sqlite")
    repository.migrate()
    paths.config_root.mkdir(parents=True)
    (paths.config_root / "naming_words.yaml").write_text(
        "summer:\n  prefix: [Golden]\n  suffix: [Horizon]\n",
        encoding="utf-8",
    )
    rejected = paths.data_root / "generated" / "rejected" / "2026-08-12"
    rejected.mkdir(parents=True)
    audio = rejected / "candidate.wav"
    audio.write_bytes(b"wav")
    audio.with_suffix(".json").write_text(
        json.dumps(
            {
                "theme": "summer_drive",
                "analysis": {
                    "duration_sec": 16,
                    "final_score": 0.76,
                    "hook_score": 0.73,
                    "loop_score": 0.71,
                    "clipping_ratio": 0,
                    "silence_ratio": 0.1,
                },
            }
        ),
        encoding="utf-8",
    )

    sources = production_audio_sources(paths, AppConfig(), repository, "summer_drive")

    assert [source.path for source in sources] == [audio]
    assert sources[0].name
    assert sources[0].slug


def test_theme_rotation_changes_by_slot(tmp_path: Path) -> None:
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

    themes = [theme_for_date(paths, AppConfig(), date(2026, 8, 12), slot) for slot in range(3)]

    assert set(themes) == {"summer_drive", "night_drive", "chill"}
