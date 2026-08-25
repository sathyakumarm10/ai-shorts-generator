"""Entry point for the AI Shorts Generator FastAPI application.

This module exposes endpoints for the backend, handling HTTP routing,
request validation, and HTTP responses/errors, while delegating job lifecycle
and asynchronous processing to the service layer.
"""

from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import ValidationError

from app.models import JobRecord, ShortsGenerationRequest, VideoJobRequest
from app.services.job_runner_service import default_job_runner
from app.services.job_service import default_job_service

# Create the FastAPI application instance.
app = FastAPI(title="AI Shorts Generator API")

# Enable CORS for frontend clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("downloads") / "uploads"
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
ALLOWED_MEDIA_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".aac", ".mp3", ".wav", ".srt", ".vtt"}


@app.get("/")
def read_root():
    """Basic endpoint to confirm the API is running."""
    return {"message": "AI Shorts Generator API is running"}


@app.get("/health")
def health_check():
    """Simple health check endpoint used to verify the service is alive."""
    return {"status": "ok"}


@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Securely upload a video file for local processing.

    Validates file extension, assigns a safe unique filename, and saves the file
    to the server's approved upload directory.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided in upload")

    original_ext = Path(file.filename).suffix.lower()
    if original_ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{original_ext}'. Allowed formats: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}",
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = f"upload_{uuid4().hex}{original_ext}"
    dest_path = UPLOAD_DIR / safe_name

    try:
        with dest_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {exc}") from exc

    file_size = dest_path.stat().st_size
    if file_size == 0:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty (0 bytes)")

    return {
        "file_path": str(dest_path.resolve()),
        "filename": file.filename,
        "file_size_bytes": file_size,
    }


@app.get("/api/media")
def get_media(file_path: str = Query(..., description="Absolute path to the generated media file")):
    """Safely stream or serve generated media assets for in-browser playback and downloads.

    Enforces strict security checks:
    - Resolves symlinks and prevents directory traversal.
    - Only serves files located within approved media directories (downloads or system temp).
    - Only serves allowed media extensions.
    - Read-only; rejects non-existent files or directories.
    """
    try:
        resolved_path = Path(file_path).resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid media file path")

    if not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="Media file not found")

    # Validate extension
    if resolved_path.suffix.lower() not in ALLOWED_MEDIA_EXTENSIONS:
        raise HTTPException(status_code=403, detail="Forbidden media file type")

    # Security check: Must reside within approved project download or temp directory
    approved_roots = [
        Path("downloads").resolve(),
        Path(tempfile.gettempdir()).resolve(),
    ]

    is_approved = any(
        resolved_path == root or root in resolved_path.parents
        for root in approved_roots
    )

    if not is_approved:
        raise HTTPException(status_code=403, detail="Access to the specified media path is forbidden")

    media_type = "video/mp4"
    if resolved_path.suffix.lower() in (".srt", ".vtt"):
        media_type = "text/plain"
    elif resolved_path.suffix.lower() in (".aac", ".mp3", ".wav"):
        media_type = f"audio/{resolved_path.suffix.lower().lstrip('.')}"

    return FileResponse(
        path=str(resolved_path),
        media_type=media_type,
        filename=resolved_path.name,
    )


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
