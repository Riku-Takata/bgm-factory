from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .paths import ServerPaths


@dataclass(frozen=True)
class ShortScene:
    visual: Path
    audio: Path
    label: str
    visual_start_sec: float = 0.0
    audio_start_sec: float = 0.0


@dataclass(frozen=True)
class MediaProbe:
    width: int
    height: int
    duration_sec: float
    has_audio: bool


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def _tool(paths: ServerPaths, name: str) -> str:
    local = paths.server_root / "tools" / "ffmpeg" / "bin" / f"{name}.exe"
    if local.is_file():
        return str(local)
    discovered = shutil.which(name)
    if discovered:
        return discovered
    raise FileNotFoundError(f"{name} was not found in the server tool directory or PATH")


def _drawtext(value: str) -> str:
    return (
        value.replace("\\", r"\\")
        .replace("'", r"\'")
        .replace(":", r"\:")
        .replace("%", r"\%")
    )


def _validate_scenes(scenes: Sequence[ShortScene]) -> None:
    if len(scenes) != 5:
        raise ValueError("A Short must contain exactly five visual scenes")
    for scene in scenes:
        if not scene.visual.is_file():
            raise FileNotFoundError(f"Scene visual not found: {scene.visual}")
        if not scene.audio.is_file():
            raise FileNotFoundError(f"Scene audio not found: {scene.audio}")
        if not scene.label.strip():
            raise ValueError("Each scene must have a label")
        if scene.audio_start_sec < 0 or scene.visual_start_sec < 0:
            raise ValueError("Scene start times cannot be negative")


def _is_still(path: Path) -> bool:
    return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}


def _segment_filter(
    scene: ShortScene,
    *,
    index: int,
    scene_count: int,
    duration_sec: float,
    fps: int,
    width: int,
    height: int,
    still: bool,
) -> str:
    frames = round(duration_sec * fps)
    fade_out = max(0.0, duration_sec - 0.15)
    title = _drawtext("SUMMER DRIVE")
    label = _drawtext(f"{index:02d} / {scene_count:02d}  {scene.label.upper()}")
    marker = _drawtext("PRIVATE VISUAL PIPELINE TEST")
    if still:
        visual = (
            "[0:v]scale=1188:2112:force_original_aspect_ratio=increase,"
            "crop=1188:2112,"
            f"zoompan=z='min(zoom+0.00035,1.08)':x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps={fps},"
        )
    else:
        visual = (
            f"[0:v]trim=duration={duration_sec:.3f},setpts=PTS-STARTPTS,fps={fps},"
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,"
        )
    return visual + (
        "eq=saturation=1.06:contrast=1.02,"
        f"fade=t=in:st=0:d=0.15,fade=t=out:st={fade_out:.2f}:d=0.15,"
        "drawbox=x=70:y=1450:w=940:h=340:color=black@0.38:t=fill,"
        f"drawtext=font='Arial':text='{marker}':x=76:y=110:"
        "fontsize=28:fontcolor=white@0.75,"
        f"drawtext=font='Arial':text='{title}':x=110:y=1505:"
        "fontsize=70:fontcolor=white,"
        f"drawtext=font='Arial':text='{label}':x=114:y=1595:"
        "fontsize=38:fontcolor=white@0.92[base];"
        f"[1:a]atrim=duration={duration_sec:.3f},asetpts=N/SR/TB,"
        f"afade=t=in:st=0:d=0.15,afade=t=out:st={fade_out:.2f}:d=0.15,"
        "loudnorm=I=-14:TP=-1.5:LRA=11,asplit=2[a][viz];"
        f"[viz]showwaves=s=820x96:mode=line:colors=white@0.70:r={fps},"
        "format=rgba[wave];[base][wave]overlay=130:1680:shortest=1[v]"
    )


def probe_video(paths: ServerPaths, video: Path, *, runner: CommandRunner = _run) -> MediaProbe:
    result = runner(
        [
            _tool(paths, "ffprobe"),
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height",
            "-of",
            "json",
            str(video),
        ]
    )
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    video_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "video"), None
    )
    if video_stream is None:
        raise RuntimeError("Rendered file has no video stream")
    return MediaProbe(
        width=int(video_stream.get("width", 0)),
        height=int(video_stream.get("height", 0)),
        duration_sec=float(payload.get("format", {}).get("duration", 0)),
        has_audio=any(stream.get("codec_type") == "audio" for stream in streams),
    )


def render_short(
    paths: ServerPaths,
    scenes: Sequence[ShortScene],
    output: Path,
    *,
    duration_sec: float = 8.0,
    fps: int = 30,
    width: int = 1080,
    height: int = 1920,
    runner: CommandRunner = _run,
) -> MediaProbe:
    _validate_scenes(scenes)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = _tool(paths, "ffmpeg")

    with tempfile.TemporaryDirectory(prefix="bgm-short-", dir=paths.data_root / "temp") as temp:
        temp_dir = Path(temp)
        segments: list[Path] = []
        for index, scene in enumerate(scenes, start=1):
            segment = temp_dir / f"segment-{index:02d}.mp4"
            still = _is_still(scene.visual)
            visual_input = ["-loop", "1", "-framerate", str(fps)] if still else [
                "-ss",
                f"{scene.visual_start_sec:.3f}",
            ]
            runner(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "warning",
                    "-y",
                    *visual_input,
                    "-i",
                    str(scene.visual.resolve()),
                    "-ss",
                    f"{scene.audio_start_sec:.3f}",
                    "-i",
                    str(scene.audio.resolve()),
                    "-filter_complex",
                    _segment_filter(
                        scene,
                        index=index,
                        scene_count=len(scenes),
                        duration_sec=duration_sec,
                        fps=fps,
                        width=width,
                        height=height,
                        still=still,
                    ),
                    "-map",
                    "[v]",
                    "-map",
                    "[a]",
                    "-frames:v",
                    str(round(duration_sec * fps)),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "20",
                    "-pix_fmt",
                    "yuv420p",
                    "-r",
                    str(fps),
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                    "-movflags",
                    "+faststart",
                    str(segment),
                ]
            )
            segments.append(segment)

        concat_file = temp_dir / "concat.txt"
        concat_file.write_text(
            "".join(f"file '{segment.as_posix()}'\n" for segment in segments),
            encoding="utf-8",
        )
        runner(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "warning",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(output),
            ]
        )

    probe = probe_video(paths, output, runner=runner)
    expected_duration = len(scenes) * duration_sec
    if (probe.width, probe.height) != (width, height):
        raise RuntimeError(f"Unexpected output dimensions: {probe.width}x{probe.height}")
    if not probe.has_audio:
        raise RuntimeError("Rendered Short has no audio stream")
    if abs(probe.duration_sec - expected_duration) > 0.75:
        raise RuntimeError(
            f"Unexpected output duration: {probe.duration_sec:.2f}s (expected {expected_duration:.2f}s)"
        )
    return probe
