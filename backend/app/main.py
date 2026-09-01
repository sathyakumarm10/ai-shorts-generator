"""Entry point for the AI Shorts Generator FastAPI application.

This module exposes endpoints for the backend, handling HTTP routing,
request validation, and HTTP responses/errors, while delegating job lifecycle
and asynchronous processing to the service layer.
"""

import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Query, Security, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import ValidationError

from app.models import (
    JobRecord,
    ShortsGenerationRequest,
    TokenResponse,
    User,
    UserCreate,
    UserLogin,
    UserResponse,
    VideoJobRequest,
)
from app.services.acceleration_service import default_acceleration_service
from app.services.auth_service import (
    default_auth_service,
    get_current_user,
    get_optional_user,
)
from app.services.job_runner_service import default_job_runner
from app.services.job_service import default_job_service
from app.services.media_storage_service import default_media_storage
from app.services.storage_service import default_storage_service, get_storage_report

# Create the FastAPI application instance.
app = FastAPI(title="AI Shorts Generator API")

# Enable CORS for frontend clients with configurable origins support
raw_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*").strip()
if raw_allowed_origins == "*" or not raw_allowed_origins:
    allowed_origins = ["*"]
else:
    allowed_origins = [orig.strip() for orig in raw_allowed_origins.split(",") if orig.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("downloads") / "uploads"
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
ALLOWED_MEDIA_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".aac", ".mp3", ".wav", ".srt", ".vtt", ".ass"}


@app.get("/")
def read_root():
    """Basic endpoint to confirm the API is running."""
    return {"message": "AI Shorts Generator API is running"}


@app.get("/health")
def health_check():
    """Simple health check endpoint used to verify the service is alive."""
    return {"status": "ok"}


@app.get("/api/system/acceleration")
def get_acceleration_status() -> Dict[str, Any]:
    """Retrieve runtime GPU/CPU hardware acceleration diagnostics and active encoder capabilities."""
    report = default_acceleration_service.get_acceleration_report()
    return {
        "cuda_available": report.cuda_available,
        "cuda_device_count": report.cuda_device_count,
        "cuda_device_names": report.cuda_device_names,
        "nvenc_available": report.nvenc_available,
        "configured_device_mode": report.configured_device_mode,
        "effective_whisper_device": report.effective_whisper_device,
        "effective_whisper_compute_type": report.effective_whisper_compute_type,
        "effective_video_encoder": report.effective_video_encoder,
    }


@app.get("/api/system/storage")
def get_storage_status() -> Dict[str, Any]:
    """Retrieve runtime object storage backend diagnostics and active capabilities."""
    report = get_storage_report(default_storage_service)
    return {
        "backend": report.backend,
        "configured_backend": report.configured_backend,
        "bucket": report.bucket,
        "region": report.region,
        "endpoint_url": report.endpoint_url,
        "public_base_url": report.public_base_url,
        "is_cloud_active": report.is_cloud_active,
        "local_fallback_enabled": report.local_fallback_enabled,
    }


# ---------------------------------------------------------------------------
# Authentication Routes
# ---------------------------------------------------------------------------


@app.post("/api/auth/register", response_model=TokenResponse)
def register(payload: UserCreate) -> TokenResponse:
    """Register a new user account with unique email and secure hashed password."""
    return default_auth_service.register_user(payload)


@app.post("/api/auth/login", response_model=TokenResponse)
def login(payload: UserLogin) -> TokenResponse:
    """Authenticate with email and password and return a JWT access token."""
    return default_auth_service.authenticate_user(payload)


@app.get("/api/auth/me", response_model=UserResponse)
def get_current_user_profile(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Return the profile of the currently authenticated user."""
    return UserResponse(
        user_id=current_user.user_id,
        email=current_user.email,
        created_at=current_user.created_at,
    )


@app.post("/api/auth/refresh", response_model=TokenResponse)
def refresh_token(current_user: User = Depends(get_current_user)) -> TokenResponse:
    """Refresh the access token for the active authenticated user."""
    from app.services.auth_service import ACCESS_TOKEN_EXPIRE_MINUTES, create_jwt_token
    expires_seconds = ACCESS_TOKEN_EXPIRE_MINUTES * 60
    token = create_jwt_token(
        payload={"sub": current_user.user_id, "email": current_user.email},
        expires_in_seconds=expires_seconds,
    )
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=expires_seconds,
        user=UserResponse(
            user_id=current_user.user_id,
            email=current_user.email,
            created_at=current_user.created_at,
        ),
    )


@app.post("/api/auth/logout")
def logout(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Logout endpoint."""
    return {"message": "Logged out successfully."}


# ---------------------------------------------------------------------------
# Media & Upload Routes
# ---------------------------------------------------------------------------


@app.post("/api/upload")
async def upload_video(
    file: UploadFile = File(...),
    current_user: Optional[User] = Depends(get_optional_user),
) -> Dict[str, Any]:
    """Securely upload a video file for local processing."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided in upload")

    original_ext = Path(file.filename).suffix.lower()
    if original_ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{original_ext}'. Allowed formats: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}",
        )

    # If authenticated, isolate upload in user-scoped subdirectory
    user_prefix = current_user.user_id if current_user else "anonymous"
    user_upload_dir = UPLOAD_DIR / user_prefix
    user_upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"upload_{uuid4().hex}{original_ext}"
    dest_path = user_upload_dir / safe_name

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
def get_media(
    file_path: Optional[str] = Query(None, description="Path or relative path to the generated media file"),
    path: Optional[str] = Query(None, description="Alternative query param for relative media path"),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Safely stream or serve generated media assets for in-browser playback and downloads."""
    target = path or file_path
    if not target or not target.strip():
        raise HTTPException(status_code=400, detail="Media file path query parameter is required")

    # If target is an S3 signed URL, redirect to cloud storage
    if target.startswith("http://") or target.startswith("https://"):
        return RedirectResponse(url=target)

    try:
        raw_path = Path(target)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid media file path")

    approved_roots = [
        default_media_storage.media_root.resolve(),
        Path("downloads").resolve(),
        Path(tempfile.gettempdir()).resolve(),
    ]

    resolved_path: Optional[Path] = None

    if raw_path.is_absolute():
        candidate = raw_path.resolve()
        for root in approved_roots:
            try:
                candidate.relative_to(root)
                resolved_path = candidate
                break
            except ValueError:
                continue
    else:
        for root in approved_roots:
            candidate = (root / raw_path).resolve()
            try:
                candidate.relative_to(root)
                if candidate.is_file():
                    resolved_path = candidate
                    break
            except ValueError:
                continue

    if resolved_path is None:
        if raw_path.is_absolute():
            raise HTTPException(status_code=403, detail="Access to the specified media path is forbidden")
        raise HTTPException(status_code=404, detail="Media file not found")

    if not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="Media file not found")

    # IDOR / User media isolation check: if path contains `jobs/{job_id}`, verify user ownership
    path_str = resolved_path.as_posix()
    if "/jobs/" in path_str:
        try:
            parts = path_str.split("/jobs/")[1].split("/")
            job_id = parts[0]
            job = default_job_service.get_job(job_id)
            if job and job.user_id:
                if not current_user or current_user.user_id != job.user_id:
                    raise HTTPException(status_code=403, detail="Forbidden: You do not own this media artifact.")
        except HTTPException:
            raise
        except Exception:
            pass

    if resolved_path.suffix.lower() not in ALLOWED_MEDIA_EXTENSIONS:
        raise HTTPException(status_code=403, detail="Forbidden media file type")

    media_type = "video/mp4"
    if resolved_path.suffix.lower() in (".srt", ".vtt", ".ass"):
        media_type = "text/plain"
    elif resolved_path.suffix.lower() in (".aac", ".mp3", ".wav"):
        media_type = f"audio/{resolved_path.suffix.lower().lstrip('.')}"

    return FileResponse(
        path=str(resolved_path),
        media_type=media_type,
        filename=resolved_path.name,
    )


# ---------------------------------------------------------------------------
# Jobs Management Routes (Multi-User Isolated)
# ---------------------------------------------------------------------------


@app.get("/api/jobs", response_model=List[JobRecord])
def list_jobs(current_user: Optional[User] = Depends(get_optional_user)) -> List[JobRecord]:
    """List jobs scoped to the current user (or legacy/all jobs if unauthenticated)."""
    user_id = current_user.user_id if current_user else None
    return default_job_service.list_jobs(user_id=user_id)


@app.post("/api/jobs", response_model=JobRecord)
def create_job(
    payload: Dict[str, Any],
    current_user: Optional[User] = Depends(get_optional_user),
) -> JobRecord:
    """Create and submit a new background shorts generation job attached to current user."""
    user_id = current_user.user_id if current_user else None
    if "clip_duration_seconds" in payload:
        try:
            data = {**payload, "user_id": user_id}
            shorts_req = ShortsGenerationRequest.model_validate(data)
        except ValidationError as exc:
            raise RequestValidationError(errors=exc.errors()) from exc
    else:
        try:
            legacy_req = VideoJobRequest.model_validate(payload)
            shorts_req = ShortsGenerationRequest(
                source=legacy_req.source,
                clip_duration_seconds=float(legacy_req.clip_duration),
                number_of_clips=legacy_req.number_of_clips,
                user_id=user_id,
            )
        except ValidationError as exc:
            raise RequestValidationError(errors=exc.errors()) from exc

    job_record = default_job_service.create_job(shorts_req, user_id=user_id)
    default_job_runner.submit_job(job_record.job_id, shorts_req)
    return job_record


@app.get("/api/jobs/{job_id}", response_model=JobRecord)
def get_job(
    job_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
) -> JobRecord:
    """Retrieve an existing job, verifying user ownership to prevent IDOR vulnerabilities."""
    job = default_job_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    # If job is owned by a user, enforce that requester matches owner
    if job.user_id:
        if not current_user or current_user.user_id != job.user_id:
            raise HTTPException(status_code=403, detail="Forbidden: You do not have access to this job.")

    return job


@app.delete("/api/jobs/{job_id}")
def delete_job(
    job_id: str,
    current_user: Optional[User] = Depends(get_optional_user),
) -> Dict[str, Any]:
    """Delete a job record and associated media artifacts, ensuring only the owner can delete it."""
    job = default_job_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.user_id and (not current_user or current_user.user_id != job.user_id):
        raise HTTPException(status_code=403, detail="Forbidden: You cannot delete another user's job.")

    default_job_service.delete_job(job_id, user_id=current_user.user_id if current_user else None)
    default_media_storage.delete_job_media(job_id)
    return {"message": "Job deleted successfully."}
