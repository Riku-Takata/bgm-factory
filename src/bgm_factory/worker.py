from __future__ import annotations

import json
import logging
import os
import signal
import threading
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler

from .runtime import initialize_runtime
from .scheduler import create_scheduler
from .service import process_next_job

logger = logging.getLogger(__name__)


def main() -> None:
    """Run the persistent scheduler and generation queue worker."""
    paths, config, repository = initialize_runtime()
    paths.log_root.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        paths.log_root / "worker.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)
    stop_event = threading.Event()
    state_lock = threading.Lock()
    worker_state = {"state": "starting", "job_id": None, "detail": None}

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    heartbeat = paths.log_root / "worker-heartbeat.json"
    recovered = repository.recover_interrupted_jobs()
    scheduler = create_scheduler(paths, config, repository)
    if config.schedule.enabled:
        scheduler.start()

    def write_heartbeat() -> None:
        while not stop_event.is_set():
            with state_lock:
                state = dict(worker_state)
            payload = {
                "timestamp": datetime.now(UTC).isoformat(),
                "pid": os.getpid(),
                "stage": "generation-worker",
                "generation_enabled": config.generation.enabled,
                **state,
                "queue": repository.queue_stats(),
            }
            temporary = heartbeat.with_suffix(".tmp")
            try:
                temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                temporary.replace(heartbeat)
            except OSError:
                logger.exception("failed to write heartbeat")
            stop_event.wait(30)

    heartbeat_thread = threading.Thread(target=write_heartbeat, name="heartbeat", daemon=True)
    heartbeat_thread.start()
    logger.info("worker started pid=%s recovered_jobs=%s", os.getpid(), recovered)
    try:
        while not stop_event.is_set():
            if not config.generation.enabled:
                with state_lock:
                    worker_state.update(state="disabled", job_id=None, detail=None)
                stop_event.wait(30)
                continue
            queued = repository.peek_job()
            if queued is None:
                with state_lock:
                    worker_state.update(state="idle", job_id=None, detail=None)
                stop_event.wait(10)
                continue
            with state_lock:
                worker_state.update(state="processing", job_id=queued.id, detail=None)
            try:
                result, decision = process_next_job(paths, config, repository)
                with state_lock:
                    worker_state.update(
                        state=result.state if result else "waiting_gpu",
                        job_id=queued.id,
                        detail=decision.reason if decision and not decision.available else None,
                    )
            except Exception as exc:  # noqa: BLE001 - the persistent worker must survive one job.
                with state_lock:
                    worker_state.update(state="error", job_id=queued.id, detail=str(exc))
                stop_event.wait(30)
                continue
            stop_event.wait(5)
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        stop_event.set()
        heartbeat_thread.join(timeout=5)
        logger.info("worker stopped")


if __name__ == "__main__":
    main()
