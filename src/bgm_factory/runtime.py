from __future__ import annotations

from dotenv import load_dotenv

from .config import AppConfig, load_config
from .db import Repository
from .paths import ServerPaths


def initialize_runtime() -> tuple[ServerPaths, AppConfig, Repository]:
    paths = ServerPaths.discover()
    for directory in paths.runtime_directories():
        directory.mkdir(parents=True, exist_ok=True)
    load_dotenv(paths.config_root / ".env", override=False)
    config = load_config(paths)
    repository = Repository(paths.data_root / "db" / "bgm-factory.sqlite")
    repository.migrate()
    return paths, config, repository
