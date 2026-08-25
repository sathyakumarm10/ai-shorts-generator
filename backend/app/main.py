"""Entry point for the AI Shorts Generator FastAPI application.

This module exposes endpoints for the backend, handling HTTP routing,
request validation, and HTTP responses/errors, while delegating job lifecycle
and asynchronous processing to the service layer.
"""

from typing import Any, Dict
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.models import JobRecord, ShortsGenerationRequest, VideoJobRequest
from app.services.job_runner_service import default_job_runner
from app.services.job_service import default_job_service

# Create the FastAPI application instance.
app = FastAPI(title="AI Shorts Generator API")


@app.get("/")
def read_root():
    """Basic endpoint to confirm the API is running."""
    return {"message": "AI Shorts Generator API is running"}


@app.get("/health")
def health_check():
    """Simple health check endpoint used to verify the service is alive."""
    return {"status": "ok"}


@app.post("/api/jobs", response_model=JobRecord)
def create_job(payload: Dict[str, Any]) -> JobRecord:
    """Create and submit a new background shorts generation job.

    FastAPI parses and validates the incoming JSON body. The job is registered
    in the job store with initial QUEUED status, submitted to the background
    thread pool executor, and returns immediately without blocking.
    """
    if "clip_duration_seconds" in payload:
        try:
            shorts_req = ShortsGenerationRequest.model_validate(payload)
        except ValidationError as exc:
            raise RequestValidationError(errors=exc.errors()) from exc
    else:
        try:
            legacy_req = VideoJobRequest.model_validate(payload)
            shorts_req = ShortsGenerationRequest(
                source=legacy_req.source,
                clip_duration_seconds=float(legacy_req.clip_duration),
                number_of_clips=legacy_req.number_of_clips,
            )
        except ValidationError as exc:
            raise RequestValidationError(errors=exc.errors()) from exc

    job_record = default_job_service.create_job(shorts_req)
    default_job_runner.submit_job(job_record.job_id, shorts_req)
    return job_record


@app.get("/api/jobs/{job_id}", response_model=JobRecord)
def get_job(job_id: str) -> JobRecord:
    """Retrieve an existing video processing job by its job ID.

    Returns the current JobRecord with stage progress and completed results if finished.
    If the job does not exist, an HTTP 404 is raised.
    """
    job = default_job_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
