from bgm_factory.config import ResourceGuardSettings
from bgm_factory.resource_guard import GpuSnapshot, ResourceGuard, parse_nvidia_smi


def test_parse_nvidia_smi() -> None:
    snapshot = parse_nvidia_smi("NVIDIA GeForce RTX 3060 Ti, 8192, 7000, 12, 41")
    assert snapshot.free_vram_mb == 7000
    assert snapshot.temperature_c == 41


def test_resource_guard_thresholds(monkeypatch) -> None:
    guard = ResourceGuard(ResourceGuardSettings())
    monkeypatch.setattr(
        guard, "snapshot", lambda: GpuSnapshot("GPU", 8192, 7000, 10, 40)
    )
    assert guard.can_start_job().available

    monkeypatch.setattr(
        guard, "snapshot", lambda: GpuSnapshot("GPU", 8192, 5000, 10, 40)
    )
    assert not guard.can_start_job().available
    assert guard.can_start_job(model_loaded=True).available
    assert guard.can_continue_batch().available
