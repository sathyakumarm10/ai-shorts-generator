"""Thread-safe Job management service with state machine transitions.

This module provides the `JobService` responsible for in-memory job persistence,
validating lifecycle state transitions, updating stage progress, and managing terminal states.
"""

from datetime import datetime, timezone
import threading
from typing import Dict, Optional, Set
from uuid import uuid4

from app.models import (
    JobProgress,
    JobRecord,
    JobStatus,
    ShortsGenerationRequest,
    ShortsGenerationResult,
    VideoJobRequest,
    VideoSource,
)


class JobError(Exception):
    """Domain exception raised when a job lifecycle operation or state transition is invalid."""

    pass


# Map of allowed transitions: current_status -> set of allowed next statuses
ALLOWED_TRANSITIONS: Dict[JobStatus, Set[JobStatus]] = {
    JobStatus.QUEUED: {
        JobStatus.INGESTING,
        JobStatus.EXTRACTING_METADATA,
        JobStatus.TRANSCRIBING,
        JobStatus.FINDING_HIGHLIGHTS,
        JobStatus.GENERATING_CLIPS,
        JobStatus.CONVERTING_VERTICAL,
        JobStatus.ADDING_CAPTIONS,
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.PROCESSING,
    },
    JobStatus.PROCESSING: {
        JobStatus.INGESTING,
        JobStatus.EXTRACTING_METADATA,
        JobStatus.TRANSCRIBING,
        JobStatus.FINDING_HIGHLIGHTS,
        JobStatus.GENERATING_CLIPS,
        JobStatus.CONVERTING_VERTICAL,
        JobStatus.ADDING_CAPTIONS,
        JobStatus.COMPLETED,
        JobStatus.FAILED,
    },
    JobStatus.INGESTING: {
        JobStatus.INGESTING,  # Progress sub-updates allowed
        JobStatus.EXTRACTING_METADATA,
        JobStatus.TRANSCRIBING,
        JobStatus.FINDING_HIGHLIGHTS,
        JobStatus.GENERATING_CLIPS,
        JobStatus.CONVERTING_VERTICAL,
        JobStatus.ADDING_CAPTIONS,
        JobStatus.COMPLETED,
        JobStatus.FAILED,
    },
    JobStatus.EXTRACTING_METADATA: {
        JobStatus.EXTRACTING_METADATA,
        JobStatus.TRANSCRIBING,
        JobStatus.FINDING_HIGHLIGHTS,
        JobStatus.GENERATING_CLIPS,
        JobStatus.CONVERTING_VERTICAL,
        JobStatus.ADDING_CAPTIONS,
        JobStatus.COMPLETED,
        JobStatus.FAILED,
    },
    JobStatus.TRANSCRIBING: {
        JobStatus.TRANSCRIBING,
        JobStatus.FINDING_HIGHLIGHTS,
        JobStatus.GENERATING_CLIPS,
        JobStatus.CONVERTING_VERTICAL,
        JobStatus.ADDING_CAPTIONS,
        JobStatus.COMPLETED,
        JobStatus.FAILED,
    },
    JobStatus.FINDING_HIGHLIGHTS: {
        JobStatus.FINDING_HIGHLIGHTS,
        JobStatus.GENERATING_CLIPS,
        JobStatus.CONVERTING_VERTICAL,
        JobStatus.ADDING_CAPTIONS,
        JobStatus.COMPLETED,
        JobStatus.FAILED,
    },
    JobStatus.GENERATING_CLIPS: {
        JobStatus.GENERATING_CLIPS,
        JobStatus.CONVERTING_VERTICAL,
        JobStatus.ADDING_CAPTIONS,
        JobStatus.COMPLETED,
        JobStatus.FAILED,
    },
    JobStatus.CONVERTING_VERTICAL: {
        JobStatus.CONVERTING_VERTICAL,
        JobStatus.CONVERTING_VERTICAL,
        JobStatus.ADDING_CAPTIONS,
        JobStatus.COMPLETED,
        JobStatus.FAILED,
    },
    JobStatus.ADDING_CAPTIONS: {
        JobStatus.ADDING_CAPTIONS,
        JobStatus.COMPLETED,
        JobStatus.FAILED,
    },
    # Terminal states cannot transition to anything
    JobStatus.COMPLETED: set(),
    JobStatus.FAILED: set(),
}


class JobService:
    """Thread-safe service managing job records and state transitions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, JobRecord] = {}

    def create_job(self, request: ShortsGenerationRequest | VideoJobRequest) -> JobRecord:
        """Create and register a new job record with initial QUEUED status."""
        job_id = str(uuid4())
        now = datetime.now(timezone.utc)

        if isinstance(request, ShortsGenerationRequest):
            source = request.source
            clip_duration = int(request.clip_duration_seconds)
            number_of_clips = request.number_of_clips
        elif isinstance(request, VideoJobRequest):
            source = request.source
            clip_duration = request.clip_duration
            number_of_clips = request.number_of_clips
        else:
            raise JobError(f"Unsupported request type for job creation: {type(request).__name__}")

        job = JobRecord(
            job_id=job_id,
            status=JobStatus.QUEUED,
            progress_percent=0.0,
            message="Job queued",
            created_at=now,
            source=source,
            clip_duration=clip_duration,
            number_of_clips=number_of_clips,
        )

        with self._lock:
            self._jobs[job_id] = job

        return job

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        """Retrieve a job record by ID in a thread-safe manner."""
        with self._lock:
            return self._jobs.get(job_id)

    def update_progress(
        self,
        job_id: str,
        status: JobStatus,
        progress_percent: float,
        message: str,
    ) -> JobRecord:
        """Update a job's status and progress percentage, enforcing valid state transitions."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobError(f"Job not found: {job_id}")

            current_status = job.status
            if current_status in (JobStatus.COMPLETED, JobStatus.FAILED):
                raise JobError(f"Cannot update progress for terminal job in {current_status} state.")

            allowed_next = ALLOWED_TRANSITIONS.get(current_status, set())
            if status != current_status and status not in allowed_next:
                raise JobError(
                    f"Invalid state transition from {current_status} to {status} for job {job_id}."
                )

            now = datetime.now(timezone.utc)
            started_at = job.started_at or now

            updated_job = job.model_copy(
                update={
                    "status": status,
                    "progress_percent": max(0.0, min(100.0, float(progress_percent))),
                    "message": message.strip() if message else job.message,
                    "started_at": started_at,
                }
            )
            self._jobs[job_id] = updated_job
            return updated_job

    def complete_job(self, job_id: str, result: ShortsGenerationResult) -> JobRecord:
        """Mark a job as successfully COMPLETED with its final result artifact."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobError(f"Job not found: {job_id}")

            if job.status == JobStatus.COMPLETED and job.result is not None:
                return job
            if job.status == JobStatus.FAILED:
                raise JobError(f"Cannot complete job already marked FAILED: {job_id}")

            now = datetime.now(timezone.utc)
            started_at = job.started_at or now

            completed_job = job.model_copy(
                update={
                    "status": JobStatus.COMPLETED,
                    "progress_percent": 100.0,
                    "message": "Job completed successfully",
                    "started_at": started_at,
                    "completed_at": now,
                    "result": result,
                }
            )
            self._jobs[job_id] = completed_job
            return completed_job

    def fail_job(self, job_id: str, error: str) -> JobRecord:
        """Mark a job as FAILED with an error description."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobError(f"Job not found: {job_id}")

            if job.status == JobStatus.FAILED:
                return job
            if job.status == JobStatus.COMPLETED:
                raise JobError(f"Cannot fail job already marked COMPLETED: {job_id}")

            now = datetime.now(timezone.utc)
            started_at = job.started_at or now
            err_msg = error.strip() if error and error.strip() else "Unknown job error occurred"

            failed_job = job.model_copy(
                update={
                    "status": JobStatus.FAILED,
                    "message": f"Job failed: {err_msg}",
                    "error": err_msg,
                    "started_at": started_at,
                    "completed_at": now,
                }
            )
            self._jobs[job_id] = failed_job
            return failed_job


# Global default instance for application-wide dependency sharing and backward compatibility
default_job_service = JobService()

# Module-level helpers for backward compatibility
def create_job(request: VideoJobRequest | ShortsGenerationRequest) -> JobRecord:
    return default_job_service.create_job(request)


def get_job(job_id: str) -> Optional[JobRecord]:
    return default_job_service.get_job(job_id)


# Proxy dictionary access to default instance
class _JobsProxy(dict):
    def __getitem__(self, key: str) -> JobRecord:
        res = default_job_service.get_job(key)
        if res is None:
            raise KeyError(key)
        return res

    def get(self, key: str, default=None):  # type: ignore
        res = default_job_service.get_job(key)
        return res if res is not None else default

    def __contains__(self, key: object) -> bool:
        return default_job_service.get_job(str(key)) is not None

    def __setitem__(self, key: str, value: JobRecord) -> None:
        with default_job_service._lock:
            default_job_service._jobs[key] = value


jobs = _JobsProxy()
