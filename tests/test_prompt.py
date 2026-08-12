from pathlib import Path

from bgm_factory.paths import ServerPaths
from bgm_factory.prompt import build_prompt


def test_prompt_is_reproducible_and_instrumental() -> None:
    app_root = Path(__file__).resolve().parents[1]
    paths = ServerPaths(
        server_root=app_root.parents[1],
        app_root=app_root,
        data_root=app_root / "data",
        config_root=app_root / "missing-config",
        log_root=app_root / "logs",
        ace_step_root=app_root / "ace-step",
    )
    first = build_prompt("summer_drive", paths, seed=42)
    second = build_prompt("summer_drive", paths, seed=42)

    assert first == second
    assert "Instrumental seamless loop" in first[0]
    assert "No vocals" in first[0]
