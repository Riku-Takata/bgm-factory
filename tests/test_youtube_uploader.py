from pathlib import Path

from bgm_factory.db import Repository
from bgm_factory.youtube_uploader import register_video, sha256_file


def test_register_video_hashes_and_deduplicates(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "factory.sqlite")
    repository.migrate()
    video = tmp_path / "short.mp4"
    video.write_bytes(b"fake mp4")

    first = register_video(repository, video, kind="short", title="Test")
    second = register_video(repository, video, kind="short", title="Test")

    assert first == second
    assert sha256_file(video)
    assert repository.next_video_for_upload().privacy_status == "private"
