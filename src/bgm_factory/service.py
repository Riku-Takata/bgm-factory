from __future__ import annotations

import logging

from .ace_step import AceStepClient
from .config import AppConfig
from .db import Repository
from .paths import ServerPaths
from .pipeline import GenerationPipeline, PipelineResult
from .resource_guard import GuardDecision, ResourceGuard

logger = logging.getLogger(__name__)


def process_next_job(
    paths: ServerPaths, config: AppConfig, repository: Repository
) -> tuple[PipelineResult | None, GuardDecision | None]:
    queued = repository.peek_job()
    if queued is None:
        return None, None
    guard = ResourceGuard(config.resource_guard)
    if queued.completed_count > 0:
        decision = guard.can_continue_batch()
    else:
        with AceStepClient(config.generation) as client:
            model_loaded = client.models_loaded()
        decision = guard.can_start_job(model_loaded=model_loaded)
    if not decision.available:
        repository.set_job_state(queued.id, "waiting_gpu", decision.reason)
        logger.info("job waiting for GPU id=%s reason=%s", queued.id, decision.reason)
        return None, decision
    job = repository.acquire_job()
    if job is None:
        return None, decision
    try:
        result = GenerationPipeline(paths, config, repository, guard).process(job)
        return result, decision
    except Exception as exc:
        logger.exception("job failed id=%s", job.id)
        repository.set_job_state(job.id, "failed", str(exc))
        raise
