from __future__ import annotations

import random
import re

from .config import load_yaml
from .db import Repository
from .paths import ServerPaths


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def generate_name(
    theme: str, seed: int, repository: Repository, paths: ServerPaths
) -> tuple[str, str]:
    dictionaries = load_yaml(paths, "naming_words.yaml")
    family = "night" if any(word in theme for word in ("night", "sleep", "rain")) else "summer"
    words = dictionaries.get(family) or next(iter(dictionaries.values()))
    generator = random.Random(seed)
    for _ in range(100):
        name = f"{generator.choice(words['prefix'])} {generator.choice(words['suffix'])}"
        if not repository.asset_name_exists(name):
            return name, slugify(name)
    name = f"{generator.choice(words['prefix'])} Signal {seed % 100000:05d}"
    return name, slugify(name)
