from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Self
from urllib.parse import urljoin

import httpx

from .config import GenerationSettings


class AceStepError(RuntimeError):
    pass


def models_from_payload(payload: dict) -> list[dict]:
    data = payload.get("data", {})
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        models = data.get("models", [])
        return models if isinstance(models, list) else []
    return []


class AceStepClient:
    def __init__(self, settings: GenerationSettings):
        host = os.environ.get("ACESTEP_API_HOST", "127.0.0.1")
        port = os.environ.get("ACESTEP_API_PORT", "8001")
        self.base_url = f"http://{host}:{port}"
        self.settings = settings
        api_key = os.environ.get("ACESTEP_API_KEY", "")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        timeout = httpx.Timeout(settings.timeout_sec, connect=10)
        self.client = httpx.Client(base_url=self.base_url, headers=headers, timeout=timeout)

    def close(self) -> None:
        self.client.close()

    def health(self) -> bool:
        try:
            return self.client.get("/health", timeout=5).is_success
        except httpx.HTTPError:
            return False

    def wait_until_ready(self, timeout_sec: int = 120) -> None:
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if self.health():
                return
            time.sleep(2)
        raise AceStepError(f"ACE-Step API did not become ready: {self.base_url}")

    def ensure_models_loaded(self) -> None:
        self.wait_until_ready()
        if self.models_loaded():
            return
        response = self.client.post(
            "/v1/init",
            json={
                "model": "acestep-v15-turbo",
                "init_llm": True,
                "lm_model_path": os.environ.get(
                    "ACESTEP_LM_MODEL_PATH", "acestep-5Hz-lm-0.6B"
                ),
            },
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 200:
            raise AceStepError(str(payload.get("error") or payload))

    def models_loaded(self) -> bool:
        if not self.health():
            return False
        response = self.client.get("/v1/models")
        response.raise_for_status()
        models = models_from_payload(response.json())
        return any(
            "acestep-v15-turbo" in str(model.get("id") or model.get("name") or "")
            and (model.get("is_loaded", True) is not False)
            for model in models
        )

    def generate(self, prompt: str, bpm: int, seed: int, destination: Path) -> dict:
        destination.parent.mkdir(parents=True, exist_ok=True)
        response = self.client.post(
            "/release_task",
            json={
                "prompt": prompt,
                "lyrics": "[Instrumental]",
                "thinking": False,
                "model": "acestep-v15-turbo",
                "bpm": bpm,
                "time_signature": "4",
                "audio_duration": self.settings.duration_sec,
                "inference_steps": self.settings.inference_steps,
                "batch_size": 1,
                "audio_format": "wav",
                "use_random_seed": False,
                "seed": seed,
            },
        )
        response.raise_for_status()
        payload = response.json()
        task_id = payload.get("data", {}).get("task_id")
        if not task_id:
            raise AceStepError(f"Generation did not return a task id: {payload}")

        deadline = time.monotonic() + self.settings.timeout_sec
        while time.monotonic() < deadline:
            time.sleep(self.settings.poll_interval_sec)
            query = self.client.post("/query_result", json={"task_id_list": [task_id]})
            query.raise_for_status()
            items = query.json().get("data") or []
            if not items:
                continue
            item = items[0]
            status = int(item.get("status", 0))
            if status == 2:
                raise AceStepError(str(item.get("error") or item.get("result") or item))
            if status != 1:
                continue
            result = item.get("result")
            files = json.loads(result) if isinstance(result, str) else result
            if not files or not files[0].get("file"):
                raise AceStepError(f"Generation succeeded without an audio file: {item}")
            file_info = files[0]
            download_url = urljoin(f"{self.base_url}/", file_info["file"].lstrip("/"))
            with self.client.stream("GET", download_url) as download:
                download.raise_for_status()
                with destination.open("wb") as handle:
                    for chunk in download.iter_bytes():
                        handle.write(chunk)
            return {
                "task_id": task_id,
                "seed": seed,
                "bpm": bpm,
                "model": file_info.get("dit_model", "acestep-v15-turbo"),
                "generation_info": file_info.get("generation_info"),
            }
        raise AceStepError(f"Generation timed out after {self.settings.timeout_sec}s: {task_id}")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
