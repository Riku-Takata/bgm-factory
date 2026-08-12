from pathlib import Path

import pytest

from bgm_factory.short_renderer import ShortScene, _drawtext, _segment_filter, _validate_scenes


def test_drawtext_escapes_filter_metacharacters() -> None:
    assert _drawtext("A:B% C's") == r"A\:B\% C\'s"


def test_short_requires_five_scenes(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    audio = tmp_path / "audio.wav"
    image.write_bytes(b"image")
    audio.write_bytes(b"audio")

    with pytest.raises(ValueError, match="exactly five"):
        _validate_scenes([ShortScene(visual=image, audio=audio, label="one")])


def test_production_filter_has_dynamic_title_and_no_private_marker(tmp_path: Path) -> None:
    scene = ShortScene(tmp_path / "clip.mp4", tmp_path / "audio.wav", "ocean road")

    rendered = _segment_filter(
        scene,
        index=1,
        scene_count=5,
        duration_sec=8,
        fps=30,
        width=1080,
        height=1920,
        still=False,
        title_text="Summer Drive",
        marker_text=None,
    )

    assert "SUMMER DRIVE" in rendered
    assert "PRIVATE" not in rendered
