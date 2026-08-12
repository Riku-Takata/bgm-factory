from pathlib import Path

from bgm_factory.paths import ServerPaths


def test_default_paths_follow_homeserver_layout(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BGM_FACTORY_HOME", str(tmp_path))
    paths = ServerPaths.discover()
    assert paths.data_root == tmp_path / "data" / "app-data" / "bgm-factory"
    assert paths.config_root == tmp_path / "config" / "bgm-factory"
    assert paths.log_root == tmp_path / "logs" / "bgm-factory"

