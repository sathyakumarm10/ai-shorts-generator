"""Pydantic models for the video processing job API.

These models describe the JSON shape that clients send to (request) and
receive from (response) the `/api/jobs` endpoint. Keeping them here, apart
from the route logic in `main.py`, makes it easy to see exactly what the
API expects and returns without reading through business logic.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, HttpUrl, TypeAdapter, model_validator


class JobStatus(str, Enum):
    """Controlled set of allowed values for a job's status."""

    QUEUED = "queued"
    INGESTING = "ingesting"
    EXTRACTING_METADATA = "extracting_metadata"
    TRANSCRIBING = "transcribing"
    FINDING_HIGHLIGHTS = "finding_highlights"
    GENERATING_CLIPS = "generating_clips"
    CONVERTING_VERTICAL = "converting_vertical"
    ADDING_CAPTIONS = "adding_captions"
    COMPLETED = "completed"
    FAILED = "failed"
    PROCESSING = "processing"


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


class TranscriptSegment(BaseModel):
    """Represents a discrete timestamped speech segment from an audio/video transcription.

    Contains start timestamp in seconds, end timestamp in seconds, and transcribed text.
    """

    start_seconds: float = Field(..., ge=0.0, description="Start timestamp of the segment in seconds.")
    end_seconds: float = Field(..., gt=0.0, description="End timestamp of the segment in seconds.")
    text: str = Field(..., min_length=1, description="Transcribed speech text content.")

    @model_validator(mode="after")
    def validate_segment(self) -> "TranscriptSegment":
        import math

        if not math.isfinite(self.start_seconds):
            raise ValueError("start_seconds must be a finite number")
        if not math.isfinite(self.end_seconds):
            raise ValueError("end_seconds must be a finite number")
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be strictly greater than start_seconds")
        if not self.text or not self.text.strip():
            raise ValueError("text cannot be empty or blank")
        return self


class TimestampedTranscript(BaseModel):
    """Represents the complete timestamped transcript of a media source.

    Contains an ordered list of non-overlapping TranscriptSegment objects.
    """

    segments: list[TranscriptSegment] = Field(
        default_factory=list,
        description="Chronologically ordered non-overlapping transcript segments.",
    )

    @model_validator(mode="after")
    def validate_segments_order_and_overlap(self) -> "TimestampedTranscript":
        for i in range(len(self.segments) - 1):
            curr_seg = self.segments[i]
            next_seg = self.segments[i + 1]
            if curr_seg.start_seconds > next_seg.start_seconds:
                raise ValueError(
                    f"Transcript segments must be chronologically ordered. "
                    f"Segment {i} starts at {curr_seg.start_seconds}s after segment {i+1} at {next_seg.start_seconds}s."
                )
            if curr_seg.end_seconds > next_seg.start_seconds + 1e-6:
                raise ValueError(
                    f"Transcript segments must not overlap. "
                    f"Segment {i} ends at {curr_seg.end_seconds}s but segment {i+1} starts at {next_seg.start_seconds}s."
                )
        return self


class HighlightScore(BaseModel):
    """Represents multi-dimensional interest scoring for a transcript segment or candidate.

    All score values are normalized floating-point numbers between 0.0 and 1.0 inclusive.
    """

    overall: float = Field(..., ge=0.0, le=1.0, description="Overall weighted highlight score (0.0 to 1.0).")
    hook: float = Field(..., ge=0.0, le=1.0, description="Attention-grabbing hook strength score (0.0 to 1.0).")
    emotion: float = Field(..., ge=0.0, le=1.0, description="Emotional intensity score (0.0 to 1.0).")
    curiosity: float = Field(..., ge=0.0, le=1.0, description="Curiosity and inquiry score (0.0 to 1.0).")
    information_density: float = Field(..., ge=0.0, le=1.0, description="Informational value density score (0.0 to 1.0).")

    @model_validator(mode="after")
    def validate_finite_scores(self) -> "HighlightScore":
        import math

        for field_name in ("overall", "hook", "emotion", "curiosity", "information_density"):
            val = getattr(self, field_name)
            if not math.isfinite(val):
                raise ValueError(f"{field_name} must be a finite number between 0.0 and 1.0")
        return self


class HighlightSource(str, Enum):
    """Source method used to discover and score the highlight candidate."""

    HEURISTIC = "heuristic"
    AI = "ai"


class HighlightCandidate(BaseModel):
    """Represents a potential short-form video clip candidate window derived from transcript segments.

    Timestamps strictly originate from boundary transcript segments.
    """

    start_seconds: float = Field(..., ge=0.0, description="Start timestamp of the candidate window in seconds.")
    end_seconds: float = Field(..., gt=0.0, description="End timestamp of the candidate window in seconds.")
    duration_seconds: float = Field(..., gt=0.0, description="Duration of the candidate window in seconds.")
    text: str = Field(..., min_length=1, description="Concatenated transcript text within this candidate window.")
    score: HighlightScore = Field(..., description="Calculated multi-dimensional highlight score.")
    # Intelligent AI enrichment fields (optional, gracefully defaults for heuristic pipeline)
    title: Optional[str] = Field(default=None, description="Catchy, descriptive title for the highlight clip.")
    viral_hook: Optional[str] = Field(default=None, description="Attention-grabbing opening hook for social shorts.")
    description: Optional[str] = Field(default=None, description="Concise synopsis of the clip content.")
    reasoning: Optional[str] = Field(default=None, description="Explanation or justification of why this moment is engaging.")
    source_type: HighlightSource = Field(default=HighlightSource.HEURISTIC, description="Detection origin (ai or heuristic).")

    @model_validator(mode="after")
    def validate_candidate(self) -> "HighlightCandidate":
        import math

        if not math.isfinite(self.start_seconds):
            raise ValueError("start_seconds must be a finite number")
        if not math.isfinite(self.end_seconds):
            raise ValueError("end_seconds must be a finite number")
        if not math.isfinite(self.duration_seconds):
            raise ValueError("duration_seconds must be a finite number")
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be strictly greater than start_seconds")
        expected_duration = self.end_seconds - self.start_seconds
        if abs(self.duration_seconds - expected_duration) > 1e-3:
            raise ValueError(
                f"duration_seconds ({self.duration_seconds}) must equal end_seconds - start_seconds ({expected_duration:.3f})"
            )
        if not self.text or not self.text.strip():
            raise ValueError("text cannot be empty or whitespace only")
        return self


class GeneratedHighlightClip(BaseModel):
    """Represents an MP4 video clip generated from a ranked highlight candidate.

    Combines the full HighlightCandidate metadata and the local path to the rendered clip.
    """

    candidate: HighlightCandidate = Field(..., description="The highlight candidate used to generate this clip.")
    file_path: str = Field(..., min_length=1, description="Local file path to the generated MP4 clip.")

    @model_validator(mode="after")
    def validate_clip_path(self) -> "GeneratedHighlightClip":
        if not self.file_path or not self.file_path.strip():
            raise ValueError("file_path cannot be empty or whitespace only")
        return self


class VerticalVideoRequest(BaseModel):
    """Request parameters for converting a video clip into a 9:16 vertical format."""

    width: int = Field(default=1080, gt=0, description="Target width in pixels (must be positive).")
    height: int = Field(default=1920, gt=0, description="Target height in pixels (must be positive).")

    @model_validator(mode="before")
    @classmethod
    def reject_bools(cls, data: object) -> object:
        if isinstance(data, dict):
            if isinstance(data.get("width"), bool) or isinstance(data.get("height"), bool):
                raise ValueError("width and height cannot be boolean values")
        elif hasattr(data, "width") and hasattr(data, "height"):
            if isinstance(getattr(data, "width"), bool) or isinstance(getattr(data, "height"), bool):
                raise ValueError("width and height cannot be boolean values")
        return data

    @model_validator(mode="after")
    def validate_aspect_ratio(self) -> "VerticalVideoRequest":
        import math

        if not math.isfinite(self.width) or not math.isfinite(self.height):
            raise ValueError("width and height must be finite numbers")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("width and height must be strictly positive")

        ratio = self.width / self.height
        target_ratio = 9.0 / 16.0
        if abs(ratio - target_ratio) > 0.01:
            raise ValueError(
                f"Aspect ratio {self.width}:{self.height} ({ratio:.4f}) does not match 9:16 ({target_ratio:.4f})"
            )
        return self


class CaptionSegment(BaseModel):
    """Represents an individual timestamped subtitle/caption segment."""

    start_seconds: float = Field(..., ge=0.0, description="Start timestamp of the caption in seconds.")
    end_seconds: float = Field(..., gt=0.0, description="End timestamp of the caption in seconds.")
    text: str = Field(..., min_length=1, description="Caption text content.")

    @model_validator(mode="after")
    def validate_segment(self) -> "CaptionSegment":
        import math

        if not math.isfinite(self.start_seconds):
            raise ValueError("start_seconds must be a finite number")
        if not math.isfinite(self.end_seconds):
            raise ValueError("end_seconds must be a finite number")
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be strictly greater than start_seconds")
        if not self.text or not self.text.strip():
            raise ValueError("text cannot be empty or whitespace only")
        return self


class CaptionTrack(BaseModel):
    """Represents a complete set of chronological, non-overlapping caption segments."""

    segments: list[CaptionSegment] = Field(
        default_factory=list,
        description="List of chronological non-overlapping caption segments.",
    )

    @model_validator(mode="after")
    def validate_track_order_and_overlap(self) -> "CaptionTrack":
        for i in range(len(self.segments) - 1):
            curr = self.segments[i]
            next_seg = self.segments[i + 1]
            if curr.start_seconds > next_seg.start_seconds:
                raise ValueError(
                    f"Caption segments must be in chronological order: segment {i} starts at "
                    f"{curr.start_seconds}s after segment {i+1} at {next_seg.start_seconds}s"
                )
            if curr.end_seconds > next_seg.start_seconds + 1e-6:
                raise ValueError(
                    f"Caption segments must not overlap: segment {i} ends at "
                    f"{curr.end_seconds}s but segment {i+1} starts at {next_seg.start_seconds}s"
                )
        return self


class ShortsGenerationRequest(BaseModel):
    """Request parameters for orchestrating end-to-end automatic Shorts generation."""

    source: VideoSource = Field(..., description="Source video to ingest and process.")
    clip_duration_seconds: float = Field(default=60.0, gt=0.0, description="Target duration of each short in seconds.")
    number_of_clips: int = Field(default=3, gt=0, description="Maximum number of candidate shorts to generate.")
    min_clip_duration: float = Field(default=30.0, gt=0.0, description="Minimum allowed clip duration in seconds.")
    max_clip_duration: float = Field(default=120.0, gt=0.0, description="Maximum allowed clip duration in seconds.")
    vertical_width: int = Field(default=1080, gt=0, description="Target vertical video width in pixels.")
    vertical_height: int = Field(default=1920, gt=0, description="Target vertical video height in pixels.")
    include_captions: bool = Field(default=True, description="Whether to generate and burn captions into the output video.")

    @model_validator(mode="before")
    @classmethod
    def reject_invalid_bools(cls, data: object) -> object:
        if isinstance(data, dict):
            for field_name in ("clip_duration_seconds", "number_of_clips", "min_clip_duration", "max_clip_duration", "vertical_width", "vertical_height"):
                if isinstance(data.get(field_name), bool):
                    raise ValueError(f"{field_name} cannot be a boolean value")
            if "include_captions" in data and not isinstance(data["include_captions"], bool):
                raise ValueError("include_captions must be a boolean value")
        return data

    @model_validator(mode="after")
    def validate_request(self) -> "ShortsGenerationRequest":
        import math

        for field_name in ("clip_duration_seconds", "min_clip_duration", "max_clip_duration", "vertical_width", "vertical_height", "number_of_clips"):
            val = getattr(self, field_name)
            if not math.isfinite(val):
                raise ValueError(f"{field_name} must be a finite number")

        if self.min_clip_duration > self.max_clip_duration:
            raise ValueError(
                f"min_clip_duration ({self.min_clip_duration}s) cannot exceed max_clip_duration ({self.max_clip_duration}s)"
            )
        if self.clip_duration_seconds < self.min_clip_duration or self.clip_duration_seconds > self.max_clip_duration:
            raise ValueError(
                f"clip_duration_seconds ({self.clip_duration_seconds}s) must be between "
                f"min_clip_duration ({self.min_clip_duration}s) and max_clip_duration ({self.max_clip_duration}s)"
            )
        if self.number_of_clips < 1:
            raise ValueError("number_of_clips must be at least 1")

        ratio = self.vertical_width / self.vertical_height
        target_ratio = 9.0 / 16.0
        if abs(ratio - target_ratio) > 0.01:
            raise ValueError(
                f"Aspect ratio {self.vertical_width}:{self.vertical_height} does not match 9:16 ({target_ratio:.4f})"
            )
        return self


class GeneratedShort(BaseModel):
    """Represents a fully generated Short video artifact through the rendering pipeline."""

    index: int = Field(..., ge=1, description="1-based sequential ranking index.")
    candidate: HighlightCandidate = Field(..., description="The highlight candidate used for this short.")
    source_clip_path: str = Field(..., min_length=1, description="File path to the initial trimmed clip.")
    vertical_clip_path: str = Field(..., min_length=1, description="File path to the 9:16 vertical video.")
    captioned_clip_path: Optional[str] = Field(default=None, description="File path to the captioned video (if captions requested).")
    final_file_path: str = Field(..., min_length=1, description="File path to the final output video deliverable.")

    @model_validator(mode="after")
    def validate_paths(self) -> "GeneratedShort":
        for path_field in ("source_clip_path", "vertical_clip_path", "final_file_path"):
            val = getattr(self, path_field)
            if not val or not val.strip():
                raise ValueError(f"{path_field} cannot be empty or whitespace only")
        if self.captioned_clip_path is not None and not self.captioned_clip_path.strip():
            raise ValueError("captioned_clip_path cannot be whitespace only when provided")
        return self


class ShortsGenerationResult(BaseModel):
    """Complete output payload from the ShortsGenerationService pipeline."""

    source_video: IngestedVideo = Field(..., description="Ingested original source video.")
    metadata: VideoMetadata = Field(..., description="Extracted video metadata.")
    transcript: TimestampedTranscript = Field(..., description="Timestamped transcription of speech.")
    candidates: list[HighlightCandidate] = Field(..., description="Ranked highlight candidates detected.")
    generated_shorts: list[GeneratedShort] = Field(..., description="Final rendered short videos.")

    @model_validator(mode="after")
    def validate_result_shorts(self) -> "ShortsGenerationResult":
        seen_indices = set()
        for idx, short in enumerate(self.generated_shorts, start=1):
            if short.index in seen_indices:
                raise ValueError(f"Duplicate short index detected: {short.index}")
            seen_indices.add(short.index)
            if short.index != idx:
                raise ValueError(f"Generated short index {short.index} must be sequential 1-based (expected {idx})")
        return self


class JobProgress(BaseModel):
    """Represents a progress update event for a background processing job."""

    status: JobStatus = Field(..., description="Current job status.")
    progress_percent: float = Field(..., ge=0.0, le=100.0, description="Progress percentage between 0 and 100.")
    message: str = Field(..., min_length=1, description="Status update message.")

    @model_validator(mode="after")
    def validate_progress(self) -> "JobProgress":
        import math

        if not math.isfinite(self.progress_percent):
            raise ValueError("progress_percent must be a finite number")
        if not self.message or not self.message.strip():
            raise ValueError("message cannot be empty or whitespace only")
        return self


class JobRecord(BaseModel):
    """Represents the complete state of a background shorts generation job in the system."""

    job_id: str = Field(..., min_length=1, description="Unique job identifier.")
    status: JobStatus = Field(..., description="Current status of the job.")
    progress_percent: float = Field(default=0.0, ge=0.0, le=100.0, description="Overall progress percentage (0-100).")
    message: str = Field(default="Job queued", min_length=1, description="Human-readable progress message.")
    created_at: datetime = Field(..., description="UTC timestamp of when the job was created.")
    started_at: Optional[datetime] = Field(default=None, description="UTC timestamp of when processing started.")
    completed_at: Optional[datetime] = Field(default=None, description="UTC timestamp of when the job finished.")
    error: Optional[str] = Field(default=None, description="Error message if the job failed.")
    result: Optional[ShortsGenerationResult] = Field(default=None, description="Pipeline result if the job succeeded.")
    # Request tracking
    source: Optional[VideoSource] = Field(default=None, description="Source video reference.")
    clip_duration: Optional[int] = Field(default=None, description="Desired duration of each clip.")
    number_of_clips: Optional[int] = Field(default=None, description="Number of clips.")

    @model_validator(mode="after")
    def validate_job_record(self) -> "JobRecord":
        import math

        if not math.isfinite(self.progress_percent):
            raise ValueError("progress_percent must be a finite number")
        if not self.job_id or not self.job_id.strip():
            raise ValueError("job_id cannot be empty or whitespace only")
        if self.status == JobStatus.COMPLETED and self.completed_at is None:
            raise ValueError("Completed jobs must contain a completed_at timestamp")
        if self.status == JobStatus.FAILED and (not self.error or not self.error.strip()):
            raise ValueError("Failed jobs must contain a non-empty error message")
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("started_at cannot be earlier than created_at")
        if self.completed_at is not None and self.started_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot be earlier than started_at")
        if self.completed_at is not None and self.completed_at < self.created_at:
            raise ValueError("completed_at cannot be earlier than created_at")
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

