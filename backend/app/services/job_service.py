"""Job service module containing business logic and storage for video jobs.

This module encapsulates job management (creation, storage, and retrieval)
apart from the HTTP layer in `main.py`. It holds the in-memory job store and
creates jobs with generated UUIDs, UTC timestamps, and initial QUEUED status.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from app.models import JobStatus, VideoJobRequest, VideoJobResponse

# In-memory store of jobs, keyed by job_id.
# This simple dictionary stores jobs for the lifetime of the process.
jobs: dict[str, VideoJobResponse] = {}


def create_job(request: VideoJobRequest) -> VideoJobResponse:
    """Create a new video processing job from a validated request.

    Generates a unique UUID4 job ID, sets the initial status to QUEUED,
    records the creation timestamp in UTC, and stores the job in the
    in-memory dictionary.
    """
    job = VideoJobResponse(
        job_id=str(uuid4()),
        status=JobStatus.QUEUED,
        video_url=request.video_url,
        clip_duration=request.clip_duration,
        number_of_clips=request.number_of_clips,
        created_at=datetime.now(timezone.utc),
    )
    jobs[job.job_id] = job
    return job


def get_job(job_id: str) -> Optional[VideoJobResponse]:
    """Retrieve a job by its job ID.

    Returns the VideoJobResponse if found, or None if the job does not exist.
    """
    return jobs.get(job_id)
