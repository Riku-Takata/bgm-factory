from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServerPaths:
    server_root: Path
    app_root: Path
    data_root: Path
    config_root: Path
    log_root: Path
    ace_step_root: Path

    @classmethod
    def discover(cls) -> ServerPaths:
        app_root = Path(__file__).resolve().parents[2]
        server_root = Path(os.environ.get("BGM_FACTORY_HOME", app_root.parents[1]))
        data_root = Path(
            os.environ.get(
                "BGM_FACTORY_DATA_DIR", server_root / "data" / "app-data" / "bgm-factory"
            )
        )
        config_root = Path(
            os.environ.get("BGM_FACTORY_CONFIG_DIR", server_root / "config" / "bgm-factory")
        )
        log_root = Path(
            os.environ.get("BGM_FACTORY_LOG_DIR", server_root / "logs" / "bgm-factory")
        )
        ace_step_root = Path(
            os.environ.get("ACESTEP_HOME", data_root / "engines" / "ACE-Step-1.5")
        )
        return cls(server_root, app_root, data_root, config_root, log_root, ace_step_root)

    def runtime_directories(self) -> tuple[Path, ...]:
        return (
            self.data_root / "db",
            self.data_root / "generated" / "rejected",
            self.data_root / "assets",
            self.data_root / "shorts",
            self.data_root / "longmix",
            self.data_root / "temp",
            self.data_root / "cache" / "uv",
            self.data_root / "cache" / "huggingface",
            self.data_root / "engines",
            self.config_root / "secrets",
            self.log_root,
        )
