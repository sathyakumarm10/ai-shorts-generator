"""Pydantic models for the video processing job API.

These models describe the JSON shape that clients send to (request) and
receive from (response) the `/api/jobs` endpoint. Keeping them here, apart
from the route logic in `main.py`, makes it easy to see exactly what the
API expects and returns without reading through business logic.
"""

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


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
    status: str = Field(..., description="Current status of the job, e.g. 'queued'.")
    video_url: HttpUrl
    clip_duration: int
    number_of_clips: int
    created_at: datetime = Field(..., description="UTC timestamp of when the job was created.")
