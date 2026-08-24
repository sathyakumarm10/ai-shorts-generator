"""Entry point for the AI Shorts Generator FastAPI application.

This module exposes a couple of basic endpoints to confirm that the backend
is set up correctly, plus an initial endpoint for creating video processing
jobs. Job creation only records the request and returns a "queued" status -
no actual video downloading, transcription, AI analysis, or FFmpeg
processing happens yet. That work will be added in later stages of the
project.
"""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI

from app.models import VideoJobRequest, VideoJobResponse

# Create the FastAPI application instance.
app = FastAPI(title="AI Shorts Generator API")

# In-memory store of jobs, keyed by job_id. This is intentionally simple -
# it only exists for the lifetime of the running process and is not backed
# by a database. It will be replaced by real persistence in a later stage.
jobs: dict[str, VideoJobResponse] = {}


@app.get("/")
def read_root():
    """Basic endpoint to confirm the API is running."""
    return {"message": "AI Shorts Generator API is running"}


@app.get("/health")
def health_check():
    """Simple health check endpoint used to verify the service is alive."""
    return {"status": "ok"}


@app.post("/api/jobs", response_model=VideoJobResponse)
def create_job(request: VideoJobRequest) -> VideoJobResponse:
    """Create a new video processing job.

    FastAPI parses and validates the incoming JSON body against
    `VideoJobRequest` automatically. If the body is missing a required
    field or fails validation (e.g. `clip_duration` outside 30-120), FastAPI
    responds with HTTP 422 before this function is even called.

    This endpoint only creates a job record with a unique ID and a
    "queued" status - it does not download or process any video.
    """
    job = VideoJobResponse(
        job_id=str(uuid4()),
        status="queued",
        video_url=request.video_url,
        clip_duration=request.clip_duration,
        number_of_clips=request.number_of_clips,
        created_at=datetime.now(timezone.utc),
    )
    jobs[job.job_id] = job
    return job
