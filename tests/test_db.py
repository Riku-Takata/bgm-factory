import hashlib
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
