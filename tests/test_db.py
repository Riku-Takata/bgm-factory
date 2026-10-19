import hashlib
from datetime import date
from pathlib import Path

from bgm_factory.db import Repository


def test_job_lifecycle_and_asset_counter(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "factory.sqlite")
    repository.migrate()
    job_id = repository.enqueue_job("summer_drive", "prompt", 2)

    job = repository.peek_job()
    assert job is not None
    assert job.id == job_id
    assert job.state == "queued"

    acquired = repository.acquire_job()
    assert acquired is not None
    assert acquired.state == "running"
    assert repository.record_candidate(job_id, accepted=True) == (1, 1)
    repository.set_job_state(job_id, "completed")

    stats = repository.queue_stats()
    assert stats["completed"] == 1
    assert repository.allocate_asset_id() == "bgm_000001"
    assert repository.allocate_asset_id() == "bgm_000002"


def test_recover_interrupted_job(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "factory.sqlite")
    repository.migrate()
    repository.enqueue_job("chill", "prompt", 1)
    repository.acquire_job()

    assert repository.recover_interrupted_jobs() == 1
    assert repository.peek_job().state == "queued"


def test_video_registration_is_idempotent_and_tracks_upload(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "factory.sqlite")
    repository.migrate()
    content_hash = hashlib.sha256(b"video").hexdigest()
    values = {
        "kind": "short",
        "title": "Test Short",
        "description": "Private upload test",
        "tags_json": "[]",
        "theme": "summer_drive",
        "output_file": str(tmp_path / "test.mp4"),
        "content_hash": content_hash,
        "privacy_status": "private",
    }

    first = repository.register_video(values)
    second = repository.register_video(values)

    assert first == second
    video = repository.next_video_for_upload()
    assert video is not None
    assert repository.begin_video_upload(video.id)
    repository.finish_video_upload(video.id, "youtube123")
    assert repository.get_video(video.id).youtube_video_id == "youtube123"


def test_dashboard_data_defaults_to_zero(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "factory.sqlite")
    repository.migrate()

    data = repository.dashboard_data()

    assert data["totals"] == {"views": 0, "likes": 0, "comments": 0}
    assert data["videos"] == []


def test_pexels_asset_metadata_is_idempotent(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "factory.sqlite")
    repository.migrate()
    values = {
        "theme": "summer_drive",
        "search_query": "coastal road",
        "pexels_video_id": 123,
        "pexels_file_id": 456,
        "local_file": str(tmp_path / "clip.mp4"),
        "content_hash": hashlib.sha256(b"clip").hexdigest(),
        "width": 1080,
        "height": 1920,
        "duration_sec": 12.0,
        "fps": 30.0,
        "photographer": "Creator",
        "photographer_url": "https://www.pexels.com/@creator",
        "source_url": "https://www.pexels.com/video/123",
        "file_url": "https://videos.pexels.com/clip.mp4",
        "license_name": "Pexels License",
        "license_url": "https://www.pexels.com/license/",
        "attribution_text": "Video by Creator on Pexels",
    }

    assert repository.upsert_pexels_asset(values) == "pexels_123"
    assert repository.upsert_pexels_asset(values) == "pexels_123"
    assert repository.pexels_asset_ids() == {123}
    assert len(repository.pexels_assets("summer_drive")) == 1
    repository.mark_pexels_assets_used(["pexels_123"])
    assert repository.pexels_assets("summer_drive")[0]["use_count"] == 1


def test_trend_snapshots_and_decisions_are_replaceable(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "factory.sqlite")
    repository.migrate()
    run_date = date(2026, 8, 12)
    snapshot = {
        "source": "search",
        "query": "chill bgm",
        "hinted_theme": "chill",
        "youtube_video_id": "video1",
        "title": "Chill BGM",
        "channel_title": "Creator",
        "published_at": "2026-08-12T00:00:00+00:00",
        "view_count": 100,
        "safe": True,
    }

    repository.replace_trend_snapshots(run_date, [snapshot])
    repository.replace_trend_snapshots(run_date, [snapshot])
    repository.replace_daily_theme_decisions(
        run_date,
        [
            {
                "slot": 0,
                "theme": "chill",
                "total_score": 0.8,
                "source": "youtube_trends",
                "reason_json": "{}",
            }
        ],
    )

    assert len(repository.trend_snapshots(run_date, safe_only=True)) == 1
    assert repository.daily_theme_decisions(run_date)[0]["theme"] == "chill"


def test_uploaded_video_channel_is_recorded(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "factory.sqlite")
    repository.migrate()
    video_id = repository.register_video(
        {
            "kind": "short",
            "title": "Channel test",
            "output_file": str(tmp_path / "video.mp4"),
            "content_hash": hashlib.sha256(b"channel-video").hexdigest(),
        }
    )

    repository.set_video_channel(video_id, "channel123")

    with repository.connect() as connection:
        channel_id = connection.execute(
            "SELECT channel_id FROM youtube_videos WHERE id = ?", (video_id,)
        ).fetchone()["channel_id"]
    assert channel_id == "channel123"
