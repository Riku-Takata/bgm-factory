from __future__ import annotations

import json
import logging
import os
import signal
import time
from datetime import UTC, datetime

from .health import check_gpu
from .paths import ServerPaths

logger = logging.getLogger(__name__)


def main() -> None:
    """Run the environment-stage worker heartbeat.

    Actual generation jobs are deliberately not started in this foundation phase.
    """
    paths = ServerPaths.discover()
    paths.log_root.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=paths.log_root / "worker.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )
    running = True

    def stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    heartbeat = paths.log_root / "worker-heartbeat.json"
    logger.info("environment worker started pid=%s", os.getpid())
    while running:
        gpu = check_gpu()
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "pid": os.getpid(),
            "stage": "environment-foundation",
            "generation_enabled": False,
            "gpu_ok": gpu.ok,
            "gpu": gpu.detail,
        }
        temporary = heartbeat.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(heartbeat)
        time.sleep(60)
    logger.info("environment worker stopped")


if __name__ == "__main__":
    main()
