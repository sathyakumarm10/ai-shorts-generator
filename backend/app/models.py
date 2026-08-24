"""Pydantic models for the video processing job API.

These models describe the JSON shape that clients send to (request) and
receive from (response) the `/api/jobs` endpoint. Keeping them here, apart
from the route logic in `main.py`, makes it easy to see exactly what the
API expects and returns without reading through business logic.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl


class JobStatus(str, Enum):
    """Controlled set of allowed values for a job's status.

    Using an enum instead of a plain string prevents typos or unexpected
    values (e.g. "Queued" or "done") from ever being stored or returned by
    the API. Inheriting from both `str` and `Enum` means each member behaves
    like a normal string at runtime, so FastAPI/Pydantic serialize it as a
    plain JSON string (e.g. "queued") rather than something like
    "JobStatus.QUEUED".

    Only job creation (status starts as QUEUED) is implemented so far.
    Transitioning a job between statuses (e.g. to PROCESSING, COMPLETED, or
    FAILED) will be added in a later stage once actual video processing
    exists.
    """

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class VideoJobRequest(BaseModel):
    """Request body for creating a new video processing job.

    FastAPI + Pydantic automatically validate incoming JSON against this
    model. If validation fails (e.g. an out-of-range value or a missing
    field), FastAPI returns an HTTP 422 response before our route code
    even runs.
    """

    video_url: HttpUrl = Field(
        ...,
        description="URL of the source video to process (e.g. a YouTube link).",
    )
    clip_duration: int = Field(
        ...,
        ge=30,
        le=120,
        description="Desired duration of each generated clip, in seconds (30-120 inclusive).",
    )
    number_of_clips: int = Field(
        ...,
        ge=1,
        le=20,
        description="Number of clips to generate from the source video (1-20 inclusive).",
    )


class VideoJobResponse(BaseModel):
    """Response body returned after a video processing job is created.

    This represents the initial state of the job. No video processing has
    happened yet - the job simply exists in memory with a "queued" status.
    """

    job_id: str = Field(..., description="Unique identifier for the job (UUID4).")
    status: JobStatus = Field(..., description="Current status of the job.")
    video_url: HttpUrl
    clip_duration: int
    number_of_clips: int
    created_at: datetime = Field(..., description="UTC timestamp of when the job was created.")
