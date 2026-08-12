from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, Field

from .paths import ServerPaths


class AppSettings(BaseModel):
    timezone: str = "Asia/Tokyo"
    auto_upload: bool = False
    auto_publish: bool = False


class GenerationSettings(BaseModel):
    enabled: bool = True
    engine: str = "ace_step"
    duration_sec: float = 16
    candidates_per_theme: int = 40
    batch_size: int = 8
    default_theme: str = "summer_drive"
    inference_steps: int = 8
    poll_interval_sec: float = 2
    timeout_sec: int = 900


class ResourceGuardSettings(BaseModel):
    gpu_utilization_max: int = 35
    min_free_vram_mb: int = 6000
    min_free_vram_loaded_mb: int = 1200
    gpu_temperature_max: int = 78
    check_interval_sec: int = 60


class AudioSettings(BaseModel):
    target_lufs: float = -14
    true_peak_db: float = -1.5


class HookSettings(BaseModel):
    duration_sec: float = 7.5
    window_step_sec: float = 0.5
    min_score: float = 0.72


class LoopSettings(BaseModel):
    crossfade_ms: int = 250
    min_score: float = 0.70


class AssetSettings(BaseModel):
    min_final_score: float = 0.75


class StorageSettings(BaseModel):
    minimum_free_gb: int = 20
    rejected_retention_days: int = 7
    uploaded_video_retention_days: int = 30


class ScheduleSettings(BaseModel):
    enabled: bool = True
    generation_hour: int = Field(default=3, ge=0, le=23)
    generation_minute: int = Field(default=15, ge=0, le=59)
    cleanup_hour: int = Field(default=4, ge=0, le=23)
    cleanup_minute: int = Field(default=0, ge=0, le=59)


class AppConfig(BaseModel):
    app: AppSettings = AppSettings()
    generation: GenerationSettings = GenerationSettings()
    resource_guard: ResourceGuardSettings = ResourceGuardSettings()
    audio: AudioSettings = AudioSettings()
    hook: HookSettings = HookSettings()
    loop: LoopSettings = LoopSettings()
    asset: AssetSettings = AssetSettings()
    storage: StorageSettings = StorageSettings()
    schedule: ScheduleSettings = ScheduleSettings()
    shorts: dict = {}
    long_mix: dict = {}
    youtube: dict = {}

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.app.timezone)


def _configured_file(paths: ServerPaths, name: str) -> Path:
    configured = paths.config_root / name
    return configured if configured.exists() else paths.app_root / "config" / name


def load_yaml(paths: ServerPaths, name: str) -> dict:
    file_path = _configured_file(paths, name)
    with file_path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_config(paths: ServerPaths | None = None) -> AppConfig:
    paths = paths or ServerPaths.discover()
    return AppConfig.model_validate(load_yaml(paths, "app.yaml"))
