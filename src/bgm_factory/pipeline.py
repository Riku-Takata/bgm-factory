from __future__ import annotations

import json
import logging
import secrets
import shutil
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from .ace_step import AceStepClient
from .audio import AudioAnalysis, AudioAnalyzer, correct_half_double_tempo
from .config import AppConfig
from .db import GenerationJob, Repository, utc_now
from .naming import generate_name
from .paths import ServerPaths
from .prompt import build_prompt
from .resource_guard import ResourceGuard

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineResult:
    job_id: str
    completed_count: int
    accepted_count: int
    state: str


class GenerationPipeline:
    def __init__(
        self,
        paths: ServerPaths,
        config: AppConfig,
        repository: Repository,
        guard: ResourceGuard,
    ):
        self.paths = paths
        self.config = config
        self.repository = repository
        self.guard = guard
        self.analyzer = AudioAnalyzer(config)

    def process(self, job: GenerationJob) -> PipelineResult:
        logger.info(
            "processing job id=%s theme=%s progress=%s/%s",
            job.id,
            job.theme,
            job.completed_count,
            job.requested_count,
        )
        completed = job.completed_count
        accepted_count = job.accepted_count
        with AceStepClient(self.config.generation) as client:
            client.ensure_models_loaded()
            while completed < job.requested_count:
                if completed > job.completed_count:
                    decision = self.guard.can_continue_batch()
                    if not decision.available:
                        self.repository.set_job_state(job.id, "waiting_gpu", decision.reason)
                        return PipelineResult(job.id, completed, accepted_count, "waiting_gpu")
                candidate_number = completed + 1
                accepted = self._process_candidate(client, job, candidate_number)
                completed, accepted_count = self.repository.record_candidate(job.id, accepted)
                self.repository.set_job_state(job.id, "running")
        self.repository.set_job_state(job.id, "completed")
        logger.info(
            "completed job id=%s candidates=%s accepted=%s", job.id, completed, accepted_count
        )
        return PipelineResult(job.id, completed, accepted_count, "completed")

    def _process_candidate(
        self, client: AceStepClient, job: GenerationJob, candidate_number: int
    ) -> bool:
        seed = secrets.randbelow(2_147_483_647)
        prompt, requested_bpm = build_prompt(job.theme, self.paths, seed)
        candidate_dir = self.paths.data_root / "generated" / job.id
        candidate_file = candidate_dir / f"candidate_{candidate_number:04d}.wav"
        logger.info(
            "generating job=%s candidate=%s seed=%s", job.id, candidate_number, seed
        )
        generation = client.generate(prompt, requested_bpm, seed, candidate_file)
        self.repository.set_job_state(job.id, "analyzing")
        normalized_file = candidate_file.with_name(f"{candidate_file.stem}_normalized.wav")
        self.analyzer.normalize(candidate_file, normalized_file)
        candidate_file.unlink(missing_ok=True)
        normalized_file.replace(candidate_file)
        analysis = self.analyzer.analyze(candidate_file)
        analysis = replace(
            analysis,
            bpm=correct_half_double_tempo(analysis.bpm, requested_bpm),
        )
        accepted = self._is_accepted(analysis)
        if accepted:
            self._store_asset(candidate_file, job.theme, prompt, generation, analysis)
        else:
            self._store_rejected(candidate_file, job, candidate_number, prompt, generation, analysis)
        logger.info(
            "evaluated job=%s candidate=%s accepted=%s final_score=%.3f",
            job.id,
            candidate_number,
            accepted,
            analysis.final_score,
        )
        return accepted

    def _is_accepted(self, analysis: AudioAnalysis) -> bool:
        return (
            analysis.final_score >= self.config.asset.min_final_score
            and analysis.hook_score >= self.config.hook.min_score
            and analysis.loop_score >= self.config.loop.min_score
            and analysis.clipping_ratio < 0.005
            and analysis.silence_ratio < 0.20
        )

    def _store_asset(
        self,
        candidate_file: Path,
        theme: str,
        prompt: str,
        generation: dict,
        analysis: AudioAnalysis,
    ) -> None:
        asset_id = self.repository.allocate_asset_id()
        name, slug = generate_name(theme, int(generation["seed"]), self.repository, self.paths)
        asset_dir = self.paths.data_root / "assets" / asset_id
        master_file = asset_dir / "master.wav"
        hook_file = asset_dir / "hook.wav"
        self.analyzer.normalize(candidate_file, master_file)
        self.analyzer.write_hook(master_file, hook_file, analysis.hook_start, analysis.hook_end)
        metadata = {
            "id": asset_id,
            "name": name,
            "slug": slug,
            "model": generation["model"],
            "seed": generation["seed"],
            "theme": theme,
            "prompt": prompt,
            "duration": analysis.duration_sec,
            "bpm": analysis.bpm,
            "hook": {
                "start": analysis.hook_start,
                "end": analysis.hook_end,
                "score": analysis.hook_score,
            },
            "loop": {
                "start": analysis.loop_start,
                "end": analysis.loop_end,
                "crossfade_ms": self.config.loop.crossfade_ms,
                "score": analysis.loop_score,
            },
            "quality_score": analysis.quality_score,
            "final_score": analysis.final_score,
            "created_at": utc_now(),
        }
        (asset_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.repository.insert_asset(
            {
                "id": asset_id,
                "name": name,
                "slug": slug,
                "theme": theme,
                "prompt": prompt,
                "model": generation["model"],
                "seed": generation["seed"],
                "bpm": analysis.bpm,
                "musical_key": None,
                "duration_sec": analysis.duration_sec,
                "master_file": str(master_file),
                "hook_file": str(hook_file),
                "hook_start": analysis.hook_start,
                "hook_end": analysis.hook_end,
                "loop_start": analysis.loop_start,
                "loop_end": analysis.loop_end,
                "loop_crossfade_ms": self.config.loop.crossfade_ms,
                "quality_score": analysis.quality_score,
                "hook_score": analysis.hook_score,
                "loop_score": analysis.loop_score,
                "final_score": analysis.final_score,
                "status": "accepted",
                "created_at": metadata["created_at"],
                "accepted_at": metadata["created_at"],
            }
        )
        candidate_file.unlink(missing_ok=True)

    def _store_rejected(
        self,
        candidate_file: Path,
        job: GenerationJob,
        candidate_number: int,
        prompt: str,
        generation: dict,
        analysis: AudioAnalysis,
    ) -> None:
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        reject_dir = self.paths.data_root / "generated" / "rejected" / day
        reject_dir.mkdir(parents=True, exist_ok=True)
        target = reject_dir / f"{job.id}_{candidate_number:04d}.wav"
        shutil.move(str(candidate_file), target)
        target.with_suffix(".json").write_text(
            json.dumps(
                {
                    "job_id": job.id,
                    "candidate_number": candidate_number,
                    "theme": job.theme,
                    "prompt": prompt,
                    "generation": generation,
                    "analysis": analysis.to_dict(),
                    "status": "rejected",
                    "created_at": utc_now(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
