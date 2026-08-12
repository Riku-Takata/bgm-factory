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
