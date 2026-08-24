"""Entry point for the AI Shorts Generator FastAPI application.

This module exposes endpoints for the backend, handling HTTP routing,
request validation, and HTTP responses/errors, while delegating job business
logic and storage to the service layer.
"""

from fastapi import FastAPI, HTTPException

from app.models import VideoJobRequest, VideoJobResponse
from app.services import job_service

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


@app.post("/api/jobs", response_model=VideoJobResponse)
def create_job(request: VideoJobRequest) -> VideoJobResponse:
    """Create a new video processing job.

    FastAPI parses and validates the incoming JSON body against
    `VideoJobRequest` automatically. If validation passes, this route
    delegates creation and storage of the job to `job_service.create_job`.
    """
    return job_service.create_job(request)


@app.get("/api/jobs/{job_id}", response_model=VideoJobResponse)
def get_job(job_id: str) -> VideoJobResponse:
    """Retrieve an existing video processing job by its job ID.

    `job_id` is extracted from the URL path. This route asks `job_service`
    for the job. If the job does not exist (`None`), an HTTP 404 is raised.
    """
    job = job_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

