from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .config import AppConfig, load_yaml
from .db import Repository
from .naming import proposed_name, slugify
from .paths import ServerPaths
from .pexels import (
    cached_theme_scenes,
    fetch_theme_assets,
    pexels_attribution_block,
)
from .short_renderer import MediaProbe, ShortScene, render_short
from .youtube_uploader import register_video

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudioSource:
    path: Path
    duration_sec: float
    score: float
    name: str
    slug: str


@dataclass(frozen=True)
class DailyShortResult:
    video_id: str
    output_file: Path
    title: str
    privacy_status: str
    pexels_asset_ids: tuple[str, ...]
    probe: MediaProbe


THEME_COPY = {
    "summer_drive": {
        "title_suffix": "Summer Drive BGM 🌊",
        "description": "Instrumental BGM for a bright summer drive.",
        "tags": ["Shorts", "BGM", "SummerDrive", "DrivingMusic"],
    },
    "night_drive": {
        "title_suffix": "Night Drive BGM 🌃",
        "description": "Instrumental BGM for a neon night drive.",
        "tags": ["Shorts", "BGM", "NightDrive", "DrivingMusic"],
    },
    "chill": {
        "title_suffix": "Chill BGM 🌿",
        "description": "Instrumental BGM for a calm break.",
        "tags": ["Shorts", "BGM", "ChillMusic", "RelaxingMusic"],
    },
    "focus_study": {
        "title_suffix": "Focus & Study BGM",
        "description": "Instrumental BGM for focus and study.",
        "tags": ["Shorts", "BGM", "FocusMusic", "StudyMusic"],
    },
    "morning_fresh": {
        "title_suffix": "Fresh Morning BGM",
        "description": "Instrumental BGM for a fresh morning.",
        "tags": ["Shorts", "BGM", "MorningMusic", "FreshStart"],
    },
    "rain_cafe": {
        "title_suffix": "Rainy Café BGM",
        "description": "Instrumental BGM for a rainy café mood.",
        "tags": ["Shorts", "BGM", "CafeMusic", "RainyDay"],
    },
    "ambient_sleep": {
        "title_suffix": "Ambient Sleep BGM",
        "description": "Ambient BGM for winding down at night.",
        "tags": ["Shorts", "BGM", "AmbientMusic", "SleepMusic"],
    },
    "workout_upbeat": {
        "title_suffix": "Upbeat Workout BGM",
        "description": "Instrumental BGM for an energetic workout.",
        "tags": ["Shorts", "BGM", "WorkoutMusic", "EnergyBoost"],
    },
}


def theme_for_date(
    paths: ServerPaths, config: AppConfig, run_date: date, slot: int = 0
) -> str:
    themes = list(load_yaml(paths, "themes.yaml"))
    if not themes:
        return config.generation.default_theme
    return themes[(run_date.toordinal() + slot) % len(themes)]


def production_audio_sources(
    paths: ServerPaths,
    config: AppConfig,
    repository: Repository,
    theme: str,
) -> list[AudioSource]:
    sources: list[AudioSource] = []
    seen: set[Path] = set()
    used_names: set[str] = set()
    for assets in (repository.bgm_assets(theme), repository.bgm_assets()):
        for asset in assets:
            path = Path(str(asset["master_file"]))
            if path.is_file() and path not in seen:
                sources.append(
                    AudioSource(
                        path,
                        float(asset["duration_sec"]),
                        float(asset["final_score"] or 0),
                        str(asset["name"]),
                        str(asset["slug"]),
                    )
                )
                seen.add(path)
                used_names.add(str(asset["name"]))

    rejected_root = paths.data_root / "generated" / "rejected"
    metadata_files = sorted(
        rejected_root.rglob("*.json") if rejected_root.exists() else (),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for metadata_file in metadata_files:
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
            analysis = metadata["analysis"]
            audio_file = metadata_file.with_suffix(".wav")
            eligible = (
                audio_file.is_file()
                and float(analysis["final_score"]) >= config.asset.min_final_score
                and float(analysis["hook_score"]) >= config.hook.min_score
                and float(analysis["loop_score"]) >= config.loop.min_score
                and float(analysis["clipping_ratio"]) < 0.005
                and float(analysis["silence_ratio"]) < 0.20
            )
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning("ignored invalid rejected-candidate metadata file=%s", metadata_file)
            continue
        if eligible and audio_file not in seen:
            seed = int(metadata.get("generation", {}).get("seed") or 0)
            name, slug = proposed_name(str(metadata.get("theme") or theme), seed, paths)
            if name in used_names:
                name = f"{name} Signal {seed % 100000:05d}"
                slug = slugify(name)
            sources.append(
                AudioSource(
                    audio_file,
                    float(analysis["duration_sec"]),
                    float(analysis["final_score"]),
                    name,
                    slug,
                )
            )
            seen.add(audio_file)
            used_names.add(name)
    return sorted(sources, key=lambda source: source.score, reverse=True)


def create_daily_short(
    paths: ServerPaths,
    config: AppConfig,
    repository: Repository,
    *,
    run_date: date,
    theme: str | None = None,
    slot: int = 0,
) -> DailyShortResult:
    if slot < 0:
        raise ValueError("slot cannot be negative")
    if theme is None:
        # Persisted decisions make generation auditable and stable even if
        # external trend results change later in the day.
        decisions = repository.daily_theme_decisions(run_date)
        selected = next((item for item in decisions if int(item["slot"]) == slot), None)
        theme = (
            str(selected["theme"])
            if selected
            else theme_for_date(paths, config, run_date, slot)
        )
    schedule_name = f"daily_public_short_{slot:02d}"
    if repository.schedule_run_exists(schedule_name, run_date):
        raise RuntimeError(f"Daily Short already created for {run_date.isoformat()}")

    if config.pexels.enabled and config.pexels.daily_downloads:
        try:
            fetch_theme_assets(
                paths,
                config,
                repository,
                theme=theme,
                limit=config.pexels.daily_downloads,
                query_offset=run_date.toordinal() + slot,
            )
        except Exception:
            logger.exception("daily Pexels refresh failed; continuing with cached footage")

    try:
        visual_assets = cached_theme_scenes(repository, theme, count=5)
    except RuntimeError:
        if not config.pexels.enabled:
            raise
        logger.info("bootstrapping five distinct Pexels scenes theme=%s", theme)
        fetch_theme_assets(paths, config, repository, theme=theme, limit=5)
        visual_assets = cached_theme_scenes(repository, theme, count=5)
    audio_sources = production_audio_sources(paths, config, repository, theme)
    if not audio_sources:
        raise RuntimeError(f"Theme {theme} has no production-eligible audio")
    scene_duration = float(config.shorts.get("target_duration_sec", 40)) / 5
    scenes: list[ShortScene] = []
    selected_tracks: list[AudioSource] = []
    track_offset = (run_date.toordinal() + slot) % len(audio_sources)
    for index, visual_asset in enumerate(visual_assets):
        track = audio_sources[(track_offset + index) % len(audio_sources)]
        selected_tracks.append(track)
        visual_room = max(0.0, float(visual_asset["duration_sec"]) - scene_duration)
        audio_room = max(0.0, track.duration_sec - scene_duration)
        scenes.append(
            ShortScene(
                visual=Path(str(visual_asset["local_file"])),
                audio=track.path,
                label=str(visual_asset["search_query"]),
                track_title=track.name,
                visual_start_sec=((run_date.toordinal() + slot * 11) * (index + 3) * 1.7)
                % (visual_room + 0.001),
                audio_start_sec=((run_date.toordinal() + slot * 7) * (index + 1) * 0.7)
                % (audio_room + 0.001),
            )
        )

    theme_config = load_yaml(paths, "themes.yaml").get(theme, {})
    display_name = str(theme_config.get("display_name") or theme.replace("_", " "))
    copy = THEME_COPY.get(
        theme,
        {
            "title_suffix": f"{display_name} BGM",
            "description": f"Instrumental BGM for {display_name}.",
            "tags": ["Shorts", "BGM"],
        },
    )
    track_names = list(dict.fromkeys(track.name for track in selected_tracks))
    lead_track = track_names[0]
    collection_label = (
        f"{lead_track} + {len(track_names) - 1} Tracks"
        if len(track_names) > 1
        else lead_track
    )
    video_title = f"{collection_label} | {copy['title_suffix']} #Shorts"
    output_slug = selected_tracks[0].slug or slugify(lead_track) or theme
    output = paths.data_root / "shorts" / run_date.isoformat() / f"{slot:02d}-{output_slug}.mp4"
    probe = render_short(
        paths,
        scenes,
        output,
        duration_sec=scene_duration,
        fps=int(config.shorts.get("fps", 30)),
        width=int(config.shorts.get("width", 1080)),
        height=int(config.shorts.get("height", 1920)),
        title_text=display_name,
        video_encoder=str(config.shorts.get("video_encoder", "libx264")),
    )
    description = (
        f"{copy['description']}\n"
        f"Tracks: {', '.join(track_names)}\n"
        "Visuals supplied by Pexels.\n\n"
        f"{pexels_attribution_block(visual_assets)}\n\n"
        "#Shorts #BGM"
    )
    video_id = register_video(
        repository,
        output,
        kind="short",
        title=video_title,
        description=description,
        tags=list(copy["tags"]),
        theme=theme,
        privacy_status=config.youtube.upload_privacy,
    )
    repository.mark_pexels_assets_used([str(asset["id"]) for asset in visual_assets])
    if not repository.record_schedule_run(schedule_name, run_date):
        raise RuntimeError(f"Daily Short was concurrently created for {run_date.isoformat()}")
    return DailyShortResult(
        video_id=video_id,
        output_file=output,
        title=video_title,
        privacy_status=config.youtube.upload_privacy,
        pexels_asset_ids=tuple(str(asset["id"]) for asset in visual_assets),
        probe=probe,
    )
