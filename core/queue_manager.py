"""Upload queue with persisted state and retry logic."""
import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

import requests.exceptions

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from uploaders.base import VideoMetadata, UploadResult
from core.exceptions import AuthenticationError, QuotaExceededError

MAX_WORKERS = 3
QUEUE_STATE_PATH = "config/queue_state.json"


def _load_queue_state(root: Path) -> list[dict]:
    path = root / QUEUE_STATE_PATH
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_queue_state(root: Path, jobs: list[dict]) -> None:
    path = root / QUEUE_STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2)


def _upload_with_retry(
    uploader_factory: Callable[[str, str], Any],
    video_path: str,
    metadata: VideoMetadata,
    profile: str,
    platform: str,
) -> UploadResult:
    """Run one platform upload with tenacity retry (no retry on auth/quota)."""
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type((
            ConnectionError,
            TimeoutError,
            OSError,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        )),
        reraise=True,
    )
    def _do() -> UploadResult:
        uploader = uploader_factory(profile, platform)
        return uploader.upload(video_path, metadata)

    try:
        return _do()
    except (AuthenticationError, QuotaExceededError):
        raise


class QueueManager:
    """Manage upload queue with ThreadPoolExecutor and retry."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path(__file__).resolve().parent.parent
        self._uploader_factory: Callable[[str, str], Any] | None = None

    def set_uploader_factory(self, factory: Callable[[str, str], Any]) -> None:
        """Set callable(profile, platform) -> BaseUploader."""
        self._uploader_factory = factory

    def add_job(
        self,
        video_path: str,
        metadata: VideoMetadata,
        platforms: list[str],
        profile: str,
    ) -> str:
        """Add a job to the queue; return job_id."""
        jobs = _load_queue_state(self._root)
        job_id = str(uuid.uuid4())
        job = {
            "job_id": job_id,
            "video_path": video_path,
            "metadata": metadata.model_dump(),
            "platforms": platforms,
            "profile": profile,
            "status": "pending",
        }
        jobs.append(job)
        _save_queue_state(self._root, jobs)
        return job_id

    def process_queue(
        self,
        video_path: str,
        metadata: VideoMetadata,
        platforms: list[str],
        profile: str,
    ) -> list[UploadResult]:
        """Run uploads for the given video to each platform concurrently (max 3 workers)."""
        if not self._uploader_factory:
            raise RuntimeError("Uploader factory not set. Call set_uploader_factory first.")
        results: list[UploadResult] = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for platform in platforms:
                try:
                    fut = executor.submit(
                        _upload_with_retry,
                        self._uploader_factory,
                        video_path,
                        metadata,
                        profile,
                        platform,
                    )
                    futures[fut] = platform
                except Exception as e:
                    results.append(UploadResult(platform=platform, success=False, error=str(e)))
            for fut in as_completed(futures):
                platform = futures[fut]
                try:
                    res = fut.result()
                    results.append(res)
                except Exception as e:
                    results.append(UploadResult(platform=platform, success=False, error=str(e)))
        return results
