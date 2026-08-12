from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from .paths import ServerPaths


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


def _command_path(name: str, extra: Path | None = None) -> str | None:
    if extra and extra.exists():
        return str(extra)
    return shutil.which(name)


def check_gpu() -> Check:
    executable = _command_path("nvidia-smi")
    if not executable:
        return Check("gpu", False, "nvidia-smi not found")
    command = [
        executable,
        "--query-gpu=name,memory.total,memory.free,utilization.gpu,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=True)
        return Check("gpu", True, result.stdout.strip())
    except (OSError, subprocess.SubprocessError) as exc:
        return Check("gpu", False, str(exc))


def check_ffmpeg(paths: ServerPaths) -> Check:
    local = paths.server_root / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    executable = _command_path("ffmpeg", local)
    if not executable:
        return Check("ffmpeg", False, "ffmpeg.exe not found")
    try:
        result = subprocess.run(
            [executable, "-version"], capture_output=True, text=True, timeout=15, check=True
        )
        return Check("ffmpeg", True, result.stdout.splitlines()[0])
    except (OSError, subprocess.SubprocessError) as exc:
        return Check("ffmpeg", False, str(exc))


def check_storage(paths: ServerPaths, minimum_free_gb: int = 20) -> Check:
    try:
        usage = shutil.disk_usage(paths.data_root)
        free_gb = usage.free / (1024**3)
        return Check("storage", free_gb >= minimum_free_gb, f"{free_gb:.1f} GiB free")
    except OSError as exc:
        return Check("storage", False, str(exc))


def check_sqlite(paths: ServerPaths) -> Check:
    db_dir = paths.data_root / "db"
    try:
        db_dir.mkdir(parents=True, exist_ok=True)
        probe = db_dir / f"health-{uuid.uuid4().hex}.sqlite"
        try:
            connection = sqlite3.connect(probe, timeout=2)
            try:
                connection.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY)")
                connection.execute("INSERT INTO probe DEFAULT VALUES")
                connection.commit()
            finally:
                connection.close()
        finally:
            probe.unlink(missing_ok=True)
        return Check("sqlite", True, f"read/write OK: {db_dir}")
    except (OSError, sqlite3.Error) as exc:
        return Check("sqlite", False, str(exc))


def check_ace_step_install(paths: ServerPaths) -> Check:
    marker = paths.ace_step_root / "pyproject.toml"
    return Check("ace_step_install", marker.exists(), str(paths.ace_step_root))


def check_ace_step_api() -> Check:
    host = os.environ.get("ACESTEP_API_HOST", "127.0.0.1")
    port = os.environ.get("ACESTEP_API_PORT", "8001")
    url = f"http://{host}:{port}/health"
    try:
        request = urllib.request.Request(url)
        api_key = os.environ.get("ACESTEP_API_KEY")
        if api_key:
            request.add_header("Authorization", f"Bearer {api_key}")
        with urllib.request.urlopen(request, timeout=3) as response:
            return Check("ace_step_api", response.status < 500, f"HTTP {response.status}: {url}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return Check("ace_step_api", False, f"not reachable: {url} ({exc})", required=False)


def check_worker(paths: ServerPaths) -> Check:
    heartbeat = paths.log_root / "worker-heartbeat.json"
    if not heartbeat.exists():
        return Check("worker", False, "heartbeat not found", required=False)
    age = max(0.0, __import__("time").time() - heartbeat.stat().st_mtime)
    return Check("worker", age <= 180, f"heartbeat age {age:.0f}s", required=False)


def run_checks() -> list[Check]:
    paths = ServerPaths.discover()
    for directory in paths.runtime_directories():
        directory.mkdir(parents=True, exist_ok=True)
    return [
        check_gpu(),
        check_ffmpeg(paths),
        check_storage(paths),
        check_sqlite(paths),
        check_ace_step_install(paths),
        check_ace_step_api(),
        check_worker(paths),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Check BGM Factory runtime prerequisites")
    parser.add_argument("--json", action="store_true", help="print machine-readable output")
    args = parser.parse_args()
    checks = run_checks()
    required_ok = all(check.ok for check in checks if check.required)
    if args.json:
        print(json.dumps({"ok": required_ok, "checks": [asdict(c) for c in checks]}, indent=2))
    else:
        for check in checks:
            state = "OK" if check.ok else ("WARN" if not check.required else "NG")
            print(f"[{state:4}] {check.name}: {check.detail}")
    raise SystemExit(0 if required_ok else 1)


if __name__ == "__main__":
    main()
