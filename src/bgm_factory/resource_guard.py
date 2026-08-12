from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from .config import ResourceGuardSettings


@dataclass(frozen=True)
class GpuSnapshot:
    name: str
    total_vram_mb: int
    free_vram_mb: int
    utilization_percent: int
    temperature_c: int


@dataclass(frozen=True)
class GuardDecision:
    available: bool
    reason: str
    snapshot: GpuSnapshot | None


def parse_nvidia_smi(output: str) -> GpuSnapshot:
    fields = [field.strip() for field in output.strip().split(",")]
    if len(fields) != 5:
        raise ValueError(f"Unexpected nvidia-smi output: {output!r}")
    return GpuSnapshot(fields[0], *(int(float(value)) for value in fields[1:]))


class ResourceGuard:
    def __init__(self, settings: ResourceGuardSettings):
        self.settings = settings

    def snapshot(self) -> GpuSnapshot:
        executable = shutil.which("nvidia-smi")
        if not executable:
            raise RuntimeError("nvidia-smi not found")
        result = subprocess.run(
            [
                executable,
                "--query-gpu=name,memory.total,memory.free,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        return parse_nvidia_smi(result.stdout.splitlines()[0])

    def can_start_job(self, model_loaded: bool = False) -> GuardDecision:
        try:
            snapshot = self.snapshot()
        except (OSError, ValueError, subprocess.SubprocessError, RuntimeError) as exc:
            return GuardDecision(False, str(exc), None)
        if snapshot.utilization_percent > self.settings.gpu_utilization_max:
            return GuardDecision(False, "GPU utilization is above threshold", snapshot)
        minimum_free = (
            self.settings.min_free_vram_loaded_mb
            if model_loaded
            else self.settings.min_free_vram_mb
        )
        if snapshot.free_vram_mb < minimum_free:
            return GuardDecision(False, "Free VRAM is below threshold", snapshot)
        if snapshot.temperature_c > self.settings.gpu_temperature_max:
            return GuardDecision(False, "GPU temperature is above threshold", snapshot)
        return GuardDecision(True, "GPU available", snapshot)

    def can_continue_batch(self) -> GuardDecision:
        """Check external load while allowing VRAM already occupied by ACE-Step itself."""
        try:
            snapshot = self.snapshot()
        except (OSError, ValueError, subprocess.SubprocessError, RuntimeError) as exc:
            return GuardDecision(False, str(exc), None)
        if snapshot.utilization_percent > self.settings.gpu_utilization_max:
            return GuardDecision(False, "GPU utilization is above threshold", snapshot)
        if snapshot.temperature_c > self.settings.gpu_temperature_max:
            return GuardDecision(False, "GPU temperature is above threshold", snapshot)
        return GuardDecision(True, "GPU available for current batch", snapshot)
