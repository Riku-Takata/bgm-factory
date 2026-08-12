from __future__ import annotations

import random

from .config import load_yaml
from .paths import ServerPaths


def build_prompt(theme: str, paths: ServerPaths, seed: int | None = None) -> tuple[str, int]:
    themes = load_yaml(paths, "themes.yaml")
    if theme not in themes:
        raise ValueError(f"Unknown theme: {theme}")
    profile = themes[theme]
    generator = random.Random(seed)
    bpm_range = profile.get("bpm", {"min": 100, "max": 130})
    bpm = generator.randint(int(bpm_range["min"]), int(bpm_range["max"]))
    keywords = ".\n".join(str(item).capitalize() for item in profile.get("keywords", []))
    avoid = ".\n".join(f"No {item}" for item in profile.get("avoid", []))
    prompt = (
        "Instrumental seamless loop.\n"
        f"{bpm} BPM.\n"
        f"{keywords}.\n"
        "Catchy repeating hook starts immediately.\n"
        "Steady energy.\n"
        f"{avoid}.\n"
        "Designed to repeat seamlessly."
    )
    return prompt, bpm
