"""Pydantic models for the video processing job API.

These models describe the JSON shape that clients send to (request) and
receive from (response) the `/api/jobs` endpoint. Keeping them here, apart
from the route logic in `main.py`, makes it easy to see exactly what the
API expects and returns without reading through business logic.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl, TypeAdapter, model_validator


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


class VideoSourceType(str, Enum):
    """Controlled set of allowed video source types.

    Specifies where the source video originates from.
    """

    YOUTUBE = "youtube"
    UPLOAD = "upload"


class VideoSource(BaseModel):
    """Represents the origin of a source video without performing processing.

    - For `youtube` sources, `location` must be a valid HTTP or HTTPS URL.
    - For `upload` sources, `location` must be a non-empty string representing
      a local file path/reference.
    """

    type: VideoSourceType = Field(..., description="The type of video source (youtube or upload).")
    location: str = Field(..., min_length=1, description="The URL or file reference for the source video.")

    @model_validator(mode="before")
    @classmethod
    def validate_source(cls, data: object) -> object:
        if isinstance(data, dict):
            source_type = data.get("type")
            location = data.get("location")
            if source_type == VideoSourceType.YOUTUBE or source_type == VideoSourceType.YOUTUBE.value:
                if location is not None:
                    TypeAdapter(HttpUrl).validate_python(location)
        elif hasattr(data, "type") and hasattr(data, "location"):
            source_type = getattr(data, "type")
            location = getattr(data, "location")
            if source_type == VideoSourceType.YOUTUBE or source_type == VideoSourceType.YOUTUBE.value:
                if location is not None:
                    TypeAdapter(HttpUrl).validate_python(location)
        return data


class IngestedVideo(BaseModel):
    """Represents a locally available video file after ingestion.

    This contains a local file path reference that can subsequently be passed
    to video processing routines (e.g. clipping, analysis).
    """

    file_path: str = Field(
        ...,
        min_length=1,
        description="Local file path or reference to the ingested video file.",
    )


class VideoMetadata(BaseModel):
    """Represents technical metadata extracted from an ingested video file.

    Provides critical video parameters (duration, dimensions, format, file size)
    required for subsequent clip segmentation, verification, and AI processing.
    """

    duration_seconds: float = Field(..., gt=0, description="Total duration of the video in seconds.")
    width: int = Field(..., gt=0, description="Width of the video stream in pixels.")
    height: int = Field(..., gt=0, description="Height of the video stream in pixels.")
    format: str = Field(..., min_length=1, description="Container/format name of the video file.")
    file_size_bytes: int = Field(..., gt=0, description="Size of the video file on disk in bytes.")


class VideoClipRequest(BaseModel):
    """Represents a request to cut a specific segment/clip from a video.

    Specifies start offset in seconds and the target clip duration (30 to 120 seconds).
    """

    start_seconds: float = Field(..., ge=0.0, description="Start timestamp of the clip in seconds.")
    duration_seconds: float = Field(
        ...,
        ge=30.0,
        le=120.0,
        description="Duration of the clip in seconds (30-120 inclusive).",
    )

    @model_validator(mode="after")
    def validate_finite_numbers(self) -> "VideoClipRequest":
        import math

        if not math.isfinite(self.start_seconds):
            raise ValueError("start_seconds must be a finite number")
        if not math.isfinite(self.duration_seconds):
            raise ValueError("duration_seconds must be a finite number")
        return self


class PlannedClip(BaseModel):
    """Represents a planned video clip segment produced by the ClipPlannerService.

    Contains 1-based indexing, start and end timestamps in seconds, and duration.
    """

    index: int = Field(..., ge=1, description="1-based positive index of the planned clip.")
    start_seconds: float = Field(..., ge=0.0, description="Start timestamp of the clip in seconds.")
    duration_seconds: float = Field(
        ...,
        ge=30.0,
        le=120.0,
        description="Duration of the clip in seconds (30-120 inclusive).",
    )
    end_seconds: float = Field(..., gt=0.0, description="End timestamp of the clip in seconds.")

    @model_validator(mode="after")
    def validate_clip(self) -> "PlannedClip":
        import math

        if not math.isfinite(self.start_seconds):
            raise ValueError("start_seconds must be a finite number")
        if not math.isfinite(self.duration_seconds):
            raise ValueError("duration_seconds must be a finite number")
        if not math.isfinite(self.end_seconds):
            raise ValueError("end_seconds must be a finite number")
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be greater than start_seconds")
        return self


class VideoJobRequest(BaseModel):
    """Request body for creating a new video processing job.

    FastAPI + Pydantic automatically validate incoming JSON against this
    model. If validation fails (e.g. an out-of-range value, invalid source,
    or a missing field), FastAPI returns an HTTP 422 response before our
    route code even runs.
    """

    source: VideoSource = Field(
        ...,
        description="Source specification for the video to process (e.g. YouTube URL or uploaded file reference).",
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
    source: VideoSource = Field(..., description="The origin and location of the source video.")
    clip_duration: int
    number_of_clips: int
    created_at: datetime = Field(..., description="UTC timestamp of when the job was created.")

