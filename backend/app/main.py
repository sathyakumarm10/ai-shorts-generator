import logging
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Security, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError

from app.models import (
    JobRecord,
    RefreshTokenRequest,
    SessionResponse,
    ShortsGenerationRequest,
    TokenResponse,
    User,
    UserCreate,
    UserLogin,
    UserResponse,
    UserRole,
    VideoJobRequest,
)
from app.services.acceleration_service import default_acceleration_service
from app.services.auth_service import (
    default_auth_service,
    get_current_user,
    get_optional_user,
    require_admin,
    require_role,
    security_bearer,
)
from app.services.db import get_database_report
from app.services.job_runner_service import default_job_runner
from app.services.job_service import default_job_service
from app.services.media_storage_service import default_media_storage
from app.services.observability import (
    default_metrics_collector,
    get_correlation_id,
    get_request_id,
    log_audit_event,
    set_correlation_id,
    set_request_id,
    setup_logging,
)
from app.services.queue_service import default_job_queue, get_queue_report
from app.services.storage_service import default_storage_service, get_storage_report

# Initialize structured logging subsystem
setup_logging()
logger = logging.getLogger(__name__)

# Create the FastAPI application instance.
app = FastAPI(title="AI Shorts Generator API")

# ---------------------------------------------------------------------------
# Observability Middleware (Request Tracing, Latency Metrics & Error Handling)
# ---------------------------------------------------------------------------


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    """Trace incoming HTTP requests with request/correlation IDs, timing metrics, and error logging."""
    req_id = request.headers.get("X-Request-ID") or uuid4().hex
    corr_id = request.headers.get("X-Correlation-ID") or req_id
    set_request_id(req_id)
    set_correlation_id(corr_id)

    start_time = time.perf_counter()
    try:
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        response.headers["X-Request-ID"] = req_id
        response.headers["X-Correlation-ID"] = corr_id
        response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"

        default_metrics_collector.record_http_request(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response
    except Exception as exc:
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        default_metrics_collector.record_http_request(
            method=request.method,
            path=request.url.path,
            status_code=500,
            duration_ms=duration_ms,
        )
        logger.exception(
            "Unhandled server exception processing %s %s: %s",
            request.method,
            request.url.path,
            exc,
            extra={"request_id": req_id, "correlation_id": corr_id},
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error", "request_id": req_id},
            headers={
                "X-Request-ID": req_id,
                "X-Correlation-ID": corr_id,
                "X-Response-Time": f"{duration_ms:.2f}ms",
            },
        )


# Enable CORS for frontend clients with secure credentials and origins configuration
raw_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*").strip()
if raw_allowed_origins == "*" or not raw_allowed_origins:
    allowed_origins = ["*"]
    allow_credentials = False
else:
    allowed_origins = [orig.strip() for orig in raw_allowed_origins.split(",") if orig.strip()]
    allow_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=allow_credentials,
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
def health_check() -> Dict[str, Any]:
    """Health check endpoint evaluating overall system readiness and individual subsystems."""
    db_rep = get_database_report()
    q_rep = get_queue_report(default_job_queue)
    storage_rep = get_storage_report(default_storage_service)
    accel_rep = default_acceleration_service.get_acceleration_report()
    metrics = default_metrics_collector.get_metrics_report()

    # Determine aggregated health status
    db_connected = db_rep.connected
    q_connected = q_rep.connected
    if not db_connected and not q_connected:
        overall_status = "unhealthy"
    elif not db_connected or not q_connected:
        overall_status = "degraded"
    else:
        overall_status = "ok"

    return {
        "status": overall_status,
        "timestamp": metrics["timestamp"],
        "uptime_seconds": metrics["uptime_seconds"],
        "version": "1.0.0",
        # Backward-compatible direct keys
        "database": {
            "backend": db_rep.backend,
            "connected": db_rep.connected,
            "migration_version": db_rep.migration_version,
        },
        "queue": {
            "backend": q_rep.backend,
            "connected": q_rep.connected,
            "pending_count": q_rep.pending_count,
        },
        # Enhanced subsystem diagnostic reports
        "subsystems": {
            "database": {
                "status": "ok" if db_connected else "error",
                "backend": db_rep.backend,
                "connected": db_rep.connected,
                "database_name": db_rep.database_name,
                "host": db_rep.host,
                "port": db_rep.port,
                "migration_version": db_rep.migration_version,
                "latency_ms": db_rep.latency_ms,
                "local_fallback_active": db_rep.local_fallback_active,
                "error": db_rep.error,
            },
            "queue": {
                "status": "ok" if q_connected else "error",
                "backend": q_rep.backend,
                "connected": q_rep.connected,
                "pending_count": q_rep.pending_count,
                "processing_count": q_rep.processing_count,
                "delayed_count": q_rep.delayed_count,
                "dead_letter_count": q_rep.dead_letter_count,
                "active_workers_count": q_rep.active_workers_count,
                "local_fallback_active": q_rep.local_fallback_active,
                "latency_ms": q_rep.latency_ms,
                "error": q_rep.error,
            },
            "storage": {
                "status": "ok",
                "backend": storage_rep.backend,
                "configured_backend": storage_rep.configured_backend,
                "bucket": storage_rep.bucket,
                "region": storage_rep.region,
                "is_cloud_active": storage_rep.is_cloud_active,
                "local_fallback_enabled": storage_rep.local_fallback_enabled,
            },
            "acceleration": {
                "status": "ok",
                "cuda_available": accel_rep.cuda_available,
                "nvenc_available": accel_rep.nvenc_available,
                "effective_whisper_device": accel_rep.effective_whisper_device,
                "effective_video_encoder": accel_rep.effective_video_encoder,
            },
        },
    }


@app.get("/api/system/metrics")
def get_system_metrics() -> Dict[str, Any]:
    """Retrieve runtime operational metrics, HTTP statistics, pipeline performance, and system resources."""
    return default_metrics_collector.get_metrics_report()



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


@app.get("/api/system/database")
def get_database_status() -> Dict[str, Any]:
    """Retrieve runtime database diagnostics and connection metrics."""
    report = get_database_report()
    return {
        "backend": report.backend,
        "configured_backend": report.configured_backend,
        "connected": report.connected,
        "database_name": report.database_name,
        "host": report.host,
        "port": report.port,
        "migration_version": report.migration_version,
        "latency_ms": report.latency_ms,
        "local_fallback_active": report.local_fallback_active,
        "error": report.error,
    }


@app.get("/api/system/queue")
def get_queue_status() -> Dict[str, Any]:
    """Retrieve runtime distributed queue diagnostics and worker health."""
    report = get_queue_report(default_job_queue)
    return {
        "backend": report.backend,
        "configured_backend": report.configured_backend,
        "connected": report.connected,
        "pending_count": report.pending_count,
        "processing_count": report.processing_count,
        "delayed_count": report.delayed_count,
        "dead_letter_count": report.dead_letter_count,
        "active_workers_count": report.active_workers_count,
        "local_fallback_active": report.local_fallback_active,
        "latency_ms": report.latency_ms,
        "error": report.error,
    }


# ---------------------------------------------------------------------------
# Authentication Routes
# ---------------------------------------------------------------------------


@app.post("/api/auth/register", response_model=TokenResponse)
def register(payload: UserCreate, request: Request) -> TokenResponse:
    """Register a new user account with unique email and secure hashed password."""
    user_agent = request.headers.get("user-agent")
    ip_addr = request.client.host if request.client else None
    result = default_auth_service.register_user(payload, user_agent=user_agent)
    log_audit_event(
        action="auth.register",
        status="success",
        user_id=result.user.user_id,
        details={"email": result.user.email, "role": result.user.role.value if hasattr(result.user.role, "value") else str(result.user.role)},
        ip_address=ip_addr,
        user_agent=user_agent,
    )
    return result


@app.post("/api/auth/login", response_model=TokenResponse)
def login(payload: UserLogin, request: Request) -> TokenResponse:
    """Authenticate with email and password and return a JWT access and refresh token pair."""
    user_agent = request.headers.get("user-agent")
    ip_addr = request.client.host if request.client else None
    result = default_auth_service.authenticate_user(payload, user_agent=user_agent)
    log_audit_event(
        action="auth.login",
        status="success",
        user_id=result.user.user_id,
        details={"email": result.user.email},
        ip_address=ip_addr,
        user_agent=user_agent,
    )
    return result


@app.get("/api/auth/me", response_model=UserResponse)
def get_current_user_profile(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Return the profile of the currently authenticated user."""
    return UserResponse(
        user_id=current_user.user_id,
        email=current_user.email,
        role=current_user.role,
        is_active=current_user.is_active,
        created_at=current_user.created_at,
    )


@app.post("/api/auth/refresh", response_model=TokenResponse)
def refresh_token(
    request: Request,
    payload: Optional[RefreshTokenRequest] = None,
    current_user: Optional[User] = Depends(get_optional_user),
) -> TokenResponse:
    """Refresh tokens: rotates refresh token or falls back to legacy Bearer refresh for backward compatibility."""
    user_agent = request.headers.get("user-agent")
    ip_addr = request.client.host if request.client else None
    if payload and payload.refresh_token:
        result = default_auth_service.refresh_tokens(payload.refresh_token, user_agent=user_agent)
        log_audit_event(
            action="auth.refresh",
            status="success",
            user_id=result.user.user_id,
            ip_address=ip_addr,
            user_agent=user_agent,
        )
        return result

    # Backward compatibility fallback for legacy clients calling /api/auth/refresh with Bearer token
    if current_user is not None:
        result = default_auth_service._issue_tokens_for_user(current_user, user_agent=user_agent)
        log_audit_event(
            action="auth.refresh_legacy",
            status="success",
            user_id=current_user.user_id,
            ip_address=ip_addr,
            user_agent=user_agent,
        )
        return result

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Refresh token payload or Bearer authentication is required.",
    )


@app.post("/api/auth/logout")
def logout(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Logout endpoint: revokes access token JTI and invalidates user sessions."""
    raw_token = credentials.credentials if credentials else None
    default_auth_service.logout_user(raw_token, current_user)
    log_audit_event(
        action="auth.logout",
        status="success",
        user_id=current_user.user_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return {"message": "Logged out successfully."}


@app.get("/api/auth/sessions", response_model=List[SessionResponse])
def list_sessions(current_user: User = Depends(get_current_user)) -> List[SessionResponse]:
    """List all active authentication sessions for the authenticated user."""
    return default_auth_service.list_user_sessions(current_user.user_id)


@app.delete("/api/auth/sessions/{token_id}")
def revoke_session(
    token_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Revoke a specific user session."""
    success = default_auth_service.revoke_session(current_user.user_id, token_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found or already revoked.")
    log_audit_event(
        action="auth.session_revoked",
        status="success",
        user_id=current_user.user_id,
        resource_id=token_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return {"message": "Session revoked successfully."}


@app.get("/api/admin/users", response_model=List[UserResponse])
def admin_list_users(
    request: Request,
    admin_user: User = Depends(require_admin),
) -> List[UserResponse]:
    """Admin-only endpoint: list all registered users (RBAC enforced)."""
    users = default_auth_service.user_store.list_all()
    log_audit_event(
        action="admin.users_list",
        status="success",
        user_id=admin_user.user_id,
        details={"returned_count": len(users)},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return [
        UserResponse(
            user_id=u.user_id,
            email=u.email,
            role=u.role,
            is_active=u.is_active,
            created_at=u.created_at,
        )
        for u in users
    ]


# ---------------------------------------------------------------------------
# Media & Upload Routes
# ---------------------------------------------------------------------------


@app.post("/api/upload")
async def upload_video(
    request: Request,
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

    default_metrics_collector.record_storage_operation("upload", bytes_count=file_size, success=True)
    log_audit_event(
        action="media.upload",
        status="success",
        user_id=user_prefix,
        resource_id=safe_name,
        details={"file_size_bytes": file_size, "filename": file.filename},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

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
    request: Request,
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
    default_metrics_collector.record_job_event("created")

    log_audit_event(
        action="job.create",
        status="success",
        user_id=user_id,
        resource_id=job_record.job_id,
        details={"clip_duration": shorts_req.clip_duration_seconds, "number_of_clips": shorts_req.number_of_clips},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

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
    request: Request,
    current_user: Optional[User] = Depends(get_optional_user),
) -> Dict[str, Any]:
    """Delete a job record and associated media artifacts, ensuring only the owner can delete it."""
    job = default_job_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.user_id and (not current_user or current_user.user_id != job.user_id):
        raise HTTPException(status_code=403, detail="Forbidden: You cannot delete another user's job.")

    user_id = current_user.user_id if current_user else None
    default_job_service.delete_job(job_id, user_id=user_id)
    default_media_storage.delete_job_media(job_id)

    log_audit_event(
        action="job.delete",
        status="success",
        user_id=user_id,
        resource_id=job_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return {"message": "Job deleted successfully."}
