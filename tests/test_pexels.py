import hashlib
from pathlib import Path

import httpx
import pytest

from bgm_factory.config import PexelsSettings
from bgm_factory.pexels import PexelsClient, _allowed_media_url, _download, pexels_attribution_block


def test_choose_file_prefers_portrait_near_1080p() -> None:
    pexels = PexelsClient(PexelsSettings(), "test", client=httpx.Client())
    video = {
        "duration": 15,
        "video_files": [
            {
                "id": 1,
                "file_type": "video/mp4",
                "width": 1920,
                "height": 1080,
                "link": "https://videos.pexels.com/landscape.mp4",
            },
            {
                "id": 2,
                "file_type": "video/mp4",
                "width": 720,
                "height": 1280,
                "link": "https://videos.pexels.com/portrait-small.mp4",
            },
            {
                "id": 3,
                "file_type": "video/mp4",
                "width": 1080,
                "height": 1920,
                "link": "https://videos.pexels.com/portrait.mp4",
            },
        ]
    }

    assert pexels.choose_file(video)["id"] == 3


def test_choose_file_rejects_too_short_video() -> None:
    pexels = PexelsClient(PexelsSettings(), "test", client=httpx.Client())
    video = {
        "duration": 3,
        "video_files": [
            {
                "id": 1,
                "file_type": "video/mp4",
                "width": 1080,
                "height": 1920,
                "link": "https://videos.pexels.com/portrait.mp4",
            }
        ],
    }

    assert pexels.choose_file(video) is None


def test_media_url_is_restricted_to_pexels_https() -> None:
    assert _allowed_media_url("https://videos.pexels.com/video.mp4")
    assert not _allowed_media_url("http://videos.pexels.com/video.mp4")
    assert not _allowed_media_url("https://pexels.com.example.org/video.mp4")


def test_download_hashes_and_cleans_partial_file(tmp_path: Path) -> None:
    content = b"pexels-video"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content, request=request)

    target = tmp_path / "clip.mp4"
    client = httpx.Client(transport=httpx.MockTransport(handler))

    digest = _download(client, "https://videos.pexels.com/clip.mp4", target, 1)

    assert digest == hashlib.sha256(content).hexdigest()
    assert target.read_bytes() == content
    assert not target.with_suffix(".mp4.part").exists()


def test_download_rejects_untrusted_host(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unsupported"):
        _download(httpx.Client(), "https://example.com/video.mp4", tmp_path / "x.mp4", 1)


def test_attribution_block_contains_source_and_license() -> None:
    block = pexels_attribution_block(
        [{"attribution_text": "Video by Creator on Pexels: https://pexels.example/video"}]
    )

    assert "Video by Creator" in block
    assert "https://www.pexels.com/license/" in block
