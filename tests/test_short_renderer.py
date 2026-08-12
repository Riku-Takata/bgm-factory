from pathlib import Path

import pytest

from bgm_factory.short_renderer import ShortScene, _drawtext, _validate_scenes


def test_drawtext_escapes_filter_metacharacters() -> None:
    assert _drawtext("A:B% C's") == r"A\:B\% C\'s"


def test_short_requires_five_scenes(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    audio = tmp_path / "audio.wav"
    image.write_bytes(b"image")
    audio.write_bytes(b"audio")

    with pytest.raises(ValueError, match="exactly five"):
        _validate_scenes([ShortScene(image=image, audio=audio, label="one")])
