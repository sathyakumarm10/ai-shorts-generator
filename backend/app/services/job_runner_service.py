"""Asynchronous job runner service using background thread pools.

This module provides the `JobRunnerService` for executing `ShortsGenerationService`
pipelines in the background without blocking FastAPI HTTP requests.
"""

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Optional

from app.models import JobStatus, ShortsGenerationRequest
from app.services.job_service import JobService, default_job_service
from app.services.shorts_generation_service import ShortsGenerationService


class JobRunnerService:
    """Service responsible for executing video processing jobs asynchronously in background threads."""

    def __init__(
        self,
        job_service: Optional[JobService] = None,
        shorts_service: Optional[ShortsGenerationService] = None,
        max_workers: int = 4,
    ) -> None:
        self.job_service = job_service or default_job_service
        self.shorts_service = shorts_service or ShortsGenerationService()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="shorts-job-runner")

    def _execute_job_pipeline(self, job_id: str, request: ShortsGenerationRequest) -> None:
        """Worker function executed inside the background thread pool."""
        def on_stage_progress(status: JobStatus, progress_percent: float, message: str) -> None:
            try:
                self.job_service.update_progress(
                    job_id=job_id,
                    status=status,
                    progress_percent=progress_percent,
                    message=message,
                )
            except Exception:
                pass

        try:
            # Initial ingestion transition
            on_stage_progress(JobStatus.INGESTING, 10.0, "Starting video ingestion")

            result = self.shorts_service.generate(
                source=request,
                progress_callback=on_stage_progress,
            )

            self.job_service.complete_job(job_id=job_id, result=result)
        except Exception as exc:
            err_msg = str(exc) or "Unexpected error during pipeline execution"
            try:
                self.job_service.fail_job(job_id=job_id, error=err_msg)
            except Exception:
                pass

    def submit_job(self, job_id: str, request: ShortsGenerationRequest) -> Future:
        """Submit a registered job for asynchronous background processing."""
        return self._executor.submit(self._execute_job_pipeline, job_id, request)

    def shutdown(self, wait: bool = False) -> None:
        """Shut down the background thread pool executor."""
        self._executor.shutdown(wait=wait)


# Global default instance
default_job_runner = JobRunnerService()
