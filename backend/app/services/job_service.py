"""Thread-safe Job management service with state machine transitions.

This module provides the `JobService` responsible for persistent job storage
(via SQLite), validating lifecycle state transitions, updating stage progress,
and managing terminal states.

Jobs survive backend restarts when a file-backed SQLite database is used.
"""

import os
from datetime import datetime, timezone
from pathlib import Path
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
from app.services.job_sqlite import SQLiteJobStore


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
    """Thread-safe service managing job records and state transitions.

    Parameters
    ----------
    db_path : str or None
        Path to the SQLite database file.  ``None`` (the default) creates an
        ephemeral in-memory database — ideal for unit tests.  Pass a file path
        for production persistence.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._lock = threading.Lock()
        self._store = SQLiteJobStore(db_path=db_path or ":memory:")

    def create_job(
        self,
        request: ShortsGenerationRequest | VideoJobRequest,
        user_id: Optional[str] = None,
    ) -> JobRecord:
        """Create and register a new job record with initial QUEUED status."""
        job_id = str(uuid4())
        now = datetime.now(timezone.utc)

        effective_user_id = user_id or getattr(request, "user_id", None)

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
            user_id=effective_user_id,
        )

        with self._lock:
            try:
                self._store.insert(job)
            except Exception as exc:
                raise JobError(f"Failed to persist new job {job_id}: {exc}") from exc

        return job

    def get_job(self, job_id: str, user_id: Optional[str] = None) -> Optional[JobRecord]:
        """Retrieve a job record by ID in a thread-safe manner, optionally checking user ownership."""
        try:
            job = self._store.get(job_id)
            if job is None:
                return None
            if user_id is not None and job.user_id is not None and job.user_id != user_id:
                return None
            return job
        except Exception as exc:
            raise JobError(f"Failed to retrieve job {job_id}: {exc}") from exc

    def list_jobs(self, user_id: Optional[str] = None) -> list[JobRecord]:
        """List jobs owned by user_id."""
        with self._lock:
            return self._store.list_by_user(user_id)

    def delete_job(self, job_id: str, user_id: Optional[str] = None) -> bool:
        """Delete a job if user owns it."""
        with self._lock:
            job = self._store.get(job_id)
            if job is None:
                return False
            if user_id is not None and job.user_id is not None and job.user_id != user_id:
                return False
            return self._store.delete(job_id)

    def update_progress(
        self,
        job_id: str,
        status: JobStatus,
        progress_percent: float,
        message: str,
    ) -> JobRecord:
        """Update a job's status and progress percentage, enforcing valid state transitions."""
        with self._lock:
            job = self._store.get(job_id)
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
            completed_at = job.completed_at
            if status in (JobStatus.COMPLETED, JobStatus.FAILED) and completed_at is None:
                completed_at = now

            updated_job = job.model_copy(
                update={
                    "status": status,
                    "progress_percent": max(0.0, min(100.0, progress_percent)),
                    "message": message.strip() if message else job.message,
                    "started_at": started_at,
                    "completed_at": completed_at,
                }
            )
            try:
                self._store.update(updated_job)
            except Exception as exc:
                raise JobError(f"Failed to persist progress update for job {job_id}: {exc}") from exc
            return updated_job

    def complete_job(self, job_id: str, result: ShortsGenerationResult) -> JobRecord:
        """Mark a job as successfully COMPLETED with its final result artifact."""
        with self._lock:
            job = self._store.get(job_id)
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
            try:
                self._store.update(completed_job)
            except Exception as exc:
                raise JobError(f"Failed to persist completion for job {job_id}: {exc}") from exc
            return completed_job

    def fail_job(self, job_id: str, error: str) -> JobRecord:
        """Mark a job as FAILED with an error description."""
        with self._lock:
            job = self._store.get(job_id)
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
            try:
                self._store.update(failed_job)
            except Exception as exc:
                raise JobError(f"Failed to persist failure for job {job_id}: {exc}") from exc
            return failed_job


# ---------------------------------------------------------------------------
# Global default instance
# ---------------------------------------------------------------------------

# Resolve the default persistent database path.
# Override with the JOB_DB_PATH environment variable if desired.
_DEFAULT_DB_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_DEFAULT_DB_PATH = os.environ.get(
    "JOB_DB_PATH",
    str(_DEFAULT_DB_DIR / "jobs.sqlite3"),
)

default_job_service = JobService(db_path=_DEFAULT_DB_PATH)


# ---------------------------------------------------------------------------
# Module-level helpers for backward compatibility
# ---------------------------------------------------------------------------

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
            default_job_service._store.upsert(value)


jobs = _JobsProxy()
