import logging
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, Security, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError

from app.models import (
    JobRecord,
    RefreshTokenRequest,
    SessionResponse,
    ShortsGenerationRequest,
    TokenResponse,
    UploadAssetResponse,
    User,
    UserCreate,
    UserLogin,
    UserResponse,
    UserRole,
    VideoJobRequest,
    VideoSourceType,
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
from app.services.media_access_service import (
    clear_media_access_cookie,
    establish_job_owner,
    owner_directory_name,
    resolve_media_owner,
)
from app.services.media_asset_service import (
    MediaAssetError,
    default_media_asset_service,
)
from app.services.media_storage_service import default_media_storage
from app.services.observability import (
    default_metrics_collector,
    get_correlation_id,
    get_request_id,
    log_audit_event,
    redact_sensitive_data,
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


def _public_media_reference(value: str) -> str:
    """Return a non-sensitive media reference suitable for API responses."""
    if value.startswith("http://") or value.startswith("https://"):
        return value

    path = Path(value)
    if not path.is_absolute():
        if ".." not in path.parts:
            return path.as_posix().lstrip("./")
        return "unavailable"

    for root in (
        default_media_storage.media_root.resolve(),
        UPLOAD_DIR.resolve(),
        Path("downloads").resolve(),
    ):
        try:
            return path.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
    return "unavailable"


def _public_job_record(job: JobRecord) -> JobRecord:
    """Strip internal ownership and host filesystem paths from a job response."""
    source = job.source
    if source is not None and source.type == VideoSourceType.UPLOAD:
        source = source.model_copy(update={"location": None})

    result = job.result
    if result is not None:
        public_source = result.source_video.model_copy(
            update={"file_path": _public_media_reference(result.source_video.file_path)}
        )
        public_shorts = []
        for short in result.generated_shorts:
            public_shorts.append(short.model_copy(update={
                "source_clip_path": _public_media_reference(short.source_clip_path),
                "vertical_clip_path": _public_media_reference(short.vertical_clip_path),
                "captioned_clip_path": (
                    _public_media_reference(short.captioned_clip_path)
                    if short.captioned_clip_path
                    else None
                ),
                "final_file_path": _public_media_reference(short.final_file_path),
            }))
        result = result.model_copy(update={
            "source_video": public_source,
            "generated_shorts": public_shorts,
        })

    error = redact_sensitive_data(job.error) if job.error else None
    if error and (
        "Traceback (most recent call last)" in error
        or "\\" in error
        or "/Users/" in error
        or "/home/" in error
    ):
        error = "Video processing failed."

    return job.model_copy(update={
        "source": source,
        "result": result,
        "error": error,
    })


def _public_diagnostic_error(error: Optional[str], subsystem: str) -> Optional[str]:
    """Keep operational diagnostics useful without returning provider details."""
    return f"{subsystem} unavailable." if error else None

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

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", str(Path("downloads") / "uploads")))
DEFAULT_MAX_UPLOAD_SIZE_BYTES = 1024 * 1024 * 1024
UPLOAD_CHUNK_SIZE_BYTES = 1024 * 1024
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
                "migration_version": db_rep.migration_version,
                "latency_ms": db_rep.latency_ms,
                "local_fallback_active": db_rep.local_fallback_active,
                "error": _public_diagnostic_error(db_rep.error, "Database"),
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
                "error": _public_diagnostic_error(q_rep.error, "Queue"),
            },
            "storage": {
                "status": "ok",
                "backend": storage_rep.backend,
                "configured_backend": storage_rep.configured_backend,
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
        "migration_version": report.migration_version,
        "latency_ms": report.latency_ms,
        "local_fallback_active": report.local_fallback_active,
        "error": _public_diagnostic_error(report.error, "Database"),
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
        "error": _public_diagnostic_error(report.error, "Queue"),
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
    response: Response,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Logout endpoint: revokes access token JTI and invalidates user sessions."""
    raw_token = credentials.credentials if credentials else None
    default_auth_service.logout_user(raw_token, current_user)
    clear_media_access_cookie(response)
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


def _max_upload_size_bytes() -> int:
    raw_value = os.environ.get("MAX_UPLOAD_SIZE_BYTES", str(DEFAULT_MAX_UPLOAD_SIZE_BYTES)).strip()
    try:
        value = int(raw_value)
    except ValueError:
        return DEFAULT_MAX_UPLOAD_SIZE_BYTES
    return value if value > 0 else DEFAULT_MAX_UPLOAD_SIZE_BYTES


@app.post("/api/upload", response_model=UploadAssetResponse)
async def upload_video(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    current_user: Optional[User] = Depends(get_optional_user),
) -> UploadAssetResponse:
    """Securely upload a video file for local processing."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided in upload")

    original_filename = file.filename.replace("\\", "/").split("/")[-1]
    original_ext = Path(original_filename).suffix.lower()
    if original_ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{original_ext}'. Allowed formats: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}",
        )

    owner_id = establish_job_owner(request, response, current_user)
    user_upload_dir = UPLOAD_DIR / owner_directory_name(owner_id)
    user_upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"asset_{uuid4().hex}{original_ext}"
    dest_path = user_upload_dir / safe_name

    file_size = 0
    max_upload_size = _max_upload_size_bytes()
    try:
        with dest_path.open("wb") as buffer:
            while chunk := await file.read(UPLOAD_CHUNK_SIZE_BYTES):
                file_size += len(chunk)
                if file_size > max_upload_size:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Uploaded file exceeds the maximum size of {max_upload_size} bytes.",
                    )
                buffer.write(chunk)
    except HTTPException:
        dest_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        logger.error("Upload write failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Failed to save uploaded file") from exc

    if file_size == 0:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty (0 bytes)")

    try:
        asset = default_media_asset_service.create_asset(
            owner_id=owner_id,
            stored_path=dest_path,
            original_filename=original_filename,
            size_bytes=file_size,
        )
    except Exception as exc:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Failed to register uploaded asset") from exc

    default_metrics_collector.record_storage_operation("upload", bytes_count=file_size, success=True)
    log_audit_event(
        action="media.upload",
        status="success",
        user_id=owner_id,
        resource_id=safe_name,
        details={"file_size_bytes": file_size, "filename": file.filename},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return UploadAssetResponse(
        asset_id=asset.asset_id,
        filename=asset.original_filename,
        file_size_bytes=file_size,
        created_at=asset.created_at,
    )


@app.get("/api/media")
def get_media(
    request: Request,
    file_path: Optional[str] = Query(None, description="Path or relative path to the generated media file"),
    path: Optional[str] = Query(None, description="Alternative query param for relative media path"),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Safely stream or serve generated media assets for in-browser playback and downloads."""
    target = path or file_path
    if not target or not target.strip():
        raise HTTPException(status_code=400, detail="Media file path query parameter is required")

    try:
        raw_path = Path(target)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid media file path")

    media_root = default_media_storage.media_root.resolve()
    upload_root = UPLOAD_DIR.resolve()
    downloads_root = Path("downloads").resolve()
    approved_roots = [media_root, upload_root, downloads_root]

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

    media_owner = resolve_media_owner(request, current_user)
    try:
        relative_media_path = resolved_path.relative_to(media_root)
    except ValueError:
        relative_media_path = None

    if relative_media_path is not None:
        parts = relative_media_path.parts
        if len(parts) < 3 or parts[0] != "jobs":
            raise HTTPException(status_code=403, detail="Media must belong to a job.")
        job = default_job_service.get_job(parts[1])
        if job is None:
            raise HTTPException(status_code=404, detail="Media job not found")
        if not job.user_id or media_owner != job.user_id:
            raise HTTPException(status_code=403, detail="Forbidden: You do not own this media artifact.")
    else:
        try:
            relative_upload_path = resolved_path.relative_to(upload_root)
        except ValueError:
            try:
                relative_download_path = resolved_path.relative_to(downloads_root)
            except ValueError:
                raise HTTPException(status_code=403, detail="Access to the specified media path is forbidden")
            owner_parts = relative_download_path.parts[1:] if (
                relative_download_path.parts and relative_download_path.parts[0] == "uploads"
            ) else ()
        else:
            owner_parts = relative_upload_path.parts

        if not media_owner or len(owner_parts) < 2 or owner_parts[0] != owner_directory_name(media_owner):
            raise HTTPException(status_code=403, detail="Forbidden: You do not own this uploaded media.")

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
def list_jobs(
    request: Request,
    response: Response,
    current_user: Optional[User] = Depends(get_optional_user),
) -> List[JobRecord]:
    """List jobs scoped to the authenticated user or anonymous browser session."""
    owner_id = establish_job_owner(request, response, current_user)
    return [_public_job_record(job) for job in default_job_service.list_jobs(user_id=owner_id)]


@app.post("/api/jobs", response_model=JobRecord)
def create_job(
    request: Request,
    response: Response,
    payload: Dict[str, Any],
    current_user: Optional[User] = Depends(get_optional_user),
) -> JobRecord:
    """Create and submit a new background shorts generation job attached to current user."""
    user_id = establish_job_owner(request, response, current_user)
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

    if shorts_req.source.type == VideoSourceType.UPLOAD:
        asset_id = shorts_req.source.asset_id
        if not asset_id or shorts_req.source.location is not None:
            raise HTTPException(
                status_code=422,
                detail="Upload jobs must reference an asset_id returned by /api/upload.",
            )
        asset = default_media_asset_service.get_asset(asset_id)
        if asset is None:
            raise HTTPException(status_code=404, detail="Uploaded asset was not found.")
        if asset.owner_id != user_id:
            raise HTTPException(status_code=403, detail="Forbidden: You do not own this uploaded asset.")
        try:
            default_media_asset_service.resolve_owned_asset(asset_id, user_id)
        except PermissionError:
            raise HTTPException(status_code=403, detail="Forbidden: You do not own this uploaded asset.")
        except MediaAssetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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

    return _public_job_record(job_record)


@app.get("/api/jobs/{job_id}", response_model=JobRecord)
def get_job(
    job_id: str,
    request: Request,
    response: Response,
    current_user: Optional[User] = Depends(get_optional_user),
) -> JobRecord:
    """Retrieve an existing job, verifying user ownership to prevent IDOR vulnerabilities."""
    job = default_job_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    owner_id = establish_job_owner(request, response, current_user)
    if not job.user_id or owner_id != job.user_id:
        raise HTTPException(status_code=403, detail="Forbidden: You do not have access to this job.")

    return _public_job_record(job)


@app.delete("/api/jobs/{job_id}")
def delete_job(
    job_id: str,
    request: Request,
    response: Response,
    current_user: Optional[User] = Depends(get_optional_user),
) -> Dict[str, Any]:
    """Delete a job record and associated media artifacts, ensuring only the owner can delete it."""
    job = default_job_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    owner_id = establish_job_owner(request, response, current_user)
    if not job.user_id or owner_id != job.user_id:
        raise HTTPException(status_code=403, detail="Forbidden: You cannot delete another user's job.")

    default_job_service.delete_job(job_id, user_id=owner_id)
    default_media_storage.delete_job_media(job_id)

    log_audit_event(
        action="job.delete",
        status="success",
        user_id=owner_id,
        resource_id=job_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return {"message": "Job deleted successfully."}
