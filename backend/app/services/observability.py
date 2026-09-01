"""Production-Grade Observability & Monitoring Service.

Provides:
- Context-propagated Request, Correlation, and Job IDs (ContextVars)
- Structured JSON logging with timestamp, context tracing, and stack trace formatting
- Automatic sensitive data redaction (passwords, JWTs, API keys, connection strings)
- Thread-safe operational metrics collector (HTTP latencies, pipeline stage durations, storage ops, system resources)
- Dedicated security and operational audit logging
- Log level configuration and initialization
"""

from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import os
import re
import sys
import threading
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

# ---------------------------------------------------------------------------
# Context Variables for Distributed / Async Tracing
# ---------------------------------------------------------------------------

request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
correlation_id_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)
job_id_var: ContextVar[Optional[str]] = ContextVar("job_id", default=None)


def get_request_id() -> Optional[str]:
    """Retrieve the active request ID from context."""
    return request_id_var.get()


def set_request_id(req_id: Optional[str]) -> None:
    """Set the active request ID in context."""
    request_id_var.set(req_id)


def get_correlation_id() -> Optional[str]:
    """Retrieve the active correlation ID from context."""
    return correlation_id_var.get()


def set_correlation_id(corr_id: Optional[str]) -> None:
    """Set the active correlation ID in context."""
    correlation_id_var.set(corr_id)


def get_job_id() -> Optional[str]:
    """Retrieve the active job ID from context."""
    return job_id_var.get()


def set_job_id(j_id: Optional[str]) -> None:
    """Set the active job ID in context."""
    job_id_var.set(j_id)


# ---------------------------------------------------------------------------
# Sensitive Data Redaction Engine
# ---------------------------------------------------------------------------

SENSITIVE_FIELD_NAMES = {
    "password",
    "password_hash",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "secret_key",
    "api_key",
    "authorization",
    "auth_token",
    "auth_jwt_secret",
    "s3_secret_access_key",
    "s3_access_key_id",
    "postgres_password",
    "redis_password",
    "openai_api_key",
    "openrouter_api_key",
}

# Regex patterns for scrubbing secrets inside string messages and URLs
REDACTION_PATTERNS = [
    # Authorization: Bearer <token>
    (re.compile(r"(Bearer\s+)[A-Za-z0-9\-_\.=]+", re.IGNORECASE), r"\1[REDACTED_TOKEN]"),
    # Refresh tokens: rt_<uuid>_<secret>
    (re.compile(r"rt_[a-f0-9\-]+_[A-Za-z0-9\-_]+", re.IGNORECASE), "[REDACTED_REFRESH_TOKEN]"),
    # PBKDF2 Password hashes: pbkdf2_sha256$...
    (re.compile(r"pbkdf2_sha256\$\d+\$[a-f0-9]+\$[a-f0-9]+", re.IGNORECASE), "[REDACTED_HASH]"),
    # PostgreSQL / DB Connection URLs with passwords: postgres://user:pass@host
    (re.compile(r"((?:postgres(?:ql)?|redis)://[^:]*:)([^@]+)(@)", re.IGNORECASE), r"\1[REDACTED_CREDENTIALS]\3"),
    # Query parameters containing keys/tokens: ?key=secret or &token=secret
    (re.compile(r"([?&](?:api_key|token|secret|password|sig|signature)=)[^&]+", re.IGNORECASE), r"\1[REDACTED]"),
]


def redact_sensitive_data(val: Any) -> Any:
    """Recursively scrub sensitive fields and token patterns from data structures."""
    if isinstance(val, dict):
        cleaned: Dict[str, Any] = {}
        for k, v in val.items():
            if str(k).lower() in SENSITIVE_FIELD_NAMES:
                cleaned[k] = "[REDACTED]"
            else:
                cleaned[k] = redact_sensitive_data(v)
        return cleaned
    elif isinstance(val, (list, tuple)):
        cleaned_list = [redact_sensitive_data(item) for item in val]
        return type(val)(cleaned_list)
    elif isinstance(val, str):
        result = val
        for pattern, replacement in REDACTION_PATTERNS:
            result = pattern.sub(replacement, result)
        return result
    return val


class RedactionFilter(logging.Filter):
    """Logging filter that scrubs sensitive information from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_sensitive_data(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = redact_sensitive_data(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(redact_sensitive_data(a) for a in record.args)
        return True


# ---------------------------------------------------------------------------
# Structured JSON Log Formatter
# ---------------------------------------------------------------------------


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as single-line structured JSON with contextual tracing."""

    def format(self, record: logging.LogRecord) -> str:
        now_utc = datetime.now(timezone.utc).isoformat()

        # Extract message with arguments formatted safely
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)

        message = redact_sensitive_data(message)

        log_data: Dict[str, Any] = {
            "timestamp": now_utc,
            "level": record.levelname,
            "logger": record.name,
            "message": message,
            "request_id": get_request_id(),
            "correlation_id": get_correlation_id(),
            "job_id": get_job_id(),
            "module": record.module,
            "line": record.lineno,
            "process": record.process,
            "thread": record.threadName,
        }

        # Include custom extra metadata passed via extra={...}
        standard_attrs = {
            "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
            "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "created", "msecs", "relativeCreated", "thread", "threadName",
            "processName", "process", "message", "asctime",
        }
        extras: Dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith("_"):
                extras[key] = redact_sensitive_data(value)

        if extras:
            log_data["extra"] = extras

        # Include exception trace if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, default=str)


# ---------------------------------------------------------------------------
# Thread-Safe Operational Metrics Collector
# ---------------------------------------------------------------------------


class MetricsCollector:
    """In-memory thread-safe metrics collector for API, pipeline, storage, and system health."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._start_time = time.time()

        # HTTP metrics
        self._http_total_requests = 0
        self._http_active_requests = 0
        self._http_status_codes: Dict[int, int] = {}
        self._http_status_categories = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
        self._http_endpoints: Dict[str, Dict[str, Any]] = {}

        # Pipeline stage duration metrics
        self._pipeline_stages: Dict[str, Dict[str, Any]] = {}

        # Job lifecycle counters
        self._jobs_created = 0
        self._jobs_completed = 0
        self._jobs_failed = 0
        self._jobs_processing = 0

        # Storage operations metrics
        self._storage_uploads = 0
        self._storage_downloads = 0
        self._storage_bytes_uploaded = 0
        self._storage_bytes_downloaded = 0
        self._storage_errors = 0
        self._storage_fallback_count = 0

        # Audit events count
        self._audit_events_count = 0

    def record_http_request(
        self,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
    ) -> None:
        """Record an incoming HTTP request execution metric."""
        with self._lock:
            self._http_total_requests += 1

            # Categorize status code
            self._http_status_codes[status_code] = self._http_status_codes.get(status_code, 0) + 1
            cat = f"{status_code // 100}xx"
            if cat in self._http_status_categories:
                self._http_status_categories[cat] += 1

            # Normalize route key
            route_key = f"{method.upper()} {path}"
            if route_key not in self._http_endpoints:
                self._http_endpoints[route_key] = {
                    "count": 0,
                    "errors": 0,
                    "total_ms": 0.0,
                    "min_ms": duration_ms,
                    "max_ms": duration_ms,
                    "recent_latencies": [],
                }

            ep = self._http_endpoints[route_key]
            ep["count"] += 1
            if status_code >= 400:
                ep["errors"] += 1
            ep["total_ms"] += duration_ms
            ep["min_ms"] = min(ep["min_ms"], duration_ms)
            ep["max_ms"] = max(ep["max_ms"], duration_ms)
            ep["recent_latencies"].append(duration_ms)
            if len(ep["recent_latencies"]) > 100:
                ep["recent_latencies"].pop(0)

    def record_stage_duration(self, stage_name: str, duration_ms: float) -> None:
        """Record execution duration for a specific pipeline processing stage."""
        with self._lock:
            if stage_name not in self._pipeline_stages:
                self._pipeline_stages[stage_name] = {
                    "count": 0,
                    "total_ms": 0.0,
                    "min_ms": duration_ms,
                    "max_ms": duration_ms,
                    "recent_latencies": [],
                }
            st = self._pipeline_stages[stage_name]
            st["count"] += 1
            st["total_ms"] += duration_ms
            st["min_ms"] = min(st["min_ms"], duration_ms)
            st["max_ms"] = max(st["max_ms"], duration_ms)
            st["recent_latencies"].append(duration_ms)
            if len(st["recent_latencies"]) > 100:
                st["recent_latencies"].pop(0)

    def record_job_event(self, event_type: str) -> None:
        """Record job lifecycle state transitions (created, completed, failed, processing)."""
        with self._lock:
            if event_type == "created":
                self._jobs_created += 1
            elif event_type == "processing":
                self._jobs_processing += 1
            elif event_type == "completed":
                self._jobs_completed += 1
                if self._jobs_processing > 0:
                    self._jobs_processing -= 1
            elif event_type == "failed":
                self._jobs_failed += 1
                if self._jobs_processing > 0:
                    self._jobs_processing -= 1

    def record_storage_operation(
        self,
        op_type: str,
        bytes_count: int = 0,
        success: bool = True,
        is_fallback: bool = False,
    ) -> None:
        """Record an object storage operation (upload or download)."""
        with self._lock:
            if op_type == "upload":
                self._storage_uploads += 1
                self._storage_bytes_uploaded += bytes_count
            elif op_type == "download":
                self._storage_downloads += 1
                self._storage_bytes_downloaded += bytes_count

            if not success:
                self._storage_errors += 1
            if is_fallback:
                self._storage_fallback_count += 1

    def record_audit_event(self) -> None:
        """Increment count of processed audit events."""
        with self._lock:
            self._audit_events_count += 1

    def get_system_resource_metrics(self) -> Dict[str, Any]:
        """Collect current process runtime memory and system metrics."""
        memory_info: Dict[str, Any] = {"rss_bytes": 0, "rss_mb": 0.0}
        try:
            import importlib
            psutil = importlib.import_module("psutil")
            process = psutil.Process()
            mem = process.memory_info()
            memory_info["rss_bytes"] = mem.rss
            memory_info["rss_mb"] = round(mem.rss / (1024 * 1024), 2)
            memory_info["vms_mb"] = round(mem.vms / (1024 * 1024), 2)
            memory_info["cpu_percent"] = process.cpu_percent(interval=None)
        except Exception:
            # Fallback when psutil is not available
            memory_info["rss_mb"] = "n/a"
            memory_info["cpu_percent"] = "n/a"

        return memory_info

    def get_metrics_report(self) -> Dict[str, Any]:
        """Compile a comprehensive structured metrics snapshot."""
        with self._lock:
            uptime_seconds = round(time.time() - self._start_time, 2)

            # Summarize endpoint latency averages
            endpoints_summary: Dict[str, Any] = {}
            for route, data in self._http_endpoints.items():
                count = data["count"]
                avg_ms = round(data["total_ms"] / count, 2) if count > 0 else 0.0
                p95_ms = 0.0
                if data["recent_latencies"]:
                    sorted_lat = sorted(data["recent_latencies"])
                    idx = int(len(sorted_lat) * 0.95)
                    p95_ms = round(sorted_lat[min(idx, len(sorted_lat) - 1)], 2)

                endpoints_summary[route] = {
                    "count": count,
                    "errors": data["errors"],
                    "min_ms": round(data["min_ms"], 2),
                    "max_ms": round(data["max_ms"], 2),
                    "avg_ms": avg_ms,
                    "p95_ms": p95_ms,
                }

            # Summarize pipeline stage durations
            stages_summary: Dict[str, Any] = {}
            for stage, data in self._pipeline_stages.items():
                count = data["count"]
                avg_ms = round(data["total_ms"] / count, 2) if count > 0 else 0.0
                stages_summary[stage] = {
                    "count": count,
                    "min_ms": round(data["min_ms"], 2),
                    "max_ms": round(data["max_ms"], 2),
                    "avg_ms": avg_ms,
                }

            return {
                "uptime_seconds": uptime_seconds,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "http": {
                    "total_requests": self._http_total_requests,
                    "status_categories": dict(self._http_status_categories),
                    "status_codes": {str(k): v for k, v in self._http_status_codes.items()},
                    "endpoints": endpoints_summary,
                },
                "pipeline": {
                    "stages": stages_summary,
                    "jobs": {
                        "created": self._jobs_created,
                        "completed": self._jobs_completed,
                        "failed": self._jobs_failed,
                        "processing": self._jobs_processing,
                    },
                },
                "storage": {
                    "uploads": self._storage_uploads,
                    "downloads": self._storage_downloads,
                    "bytes_uploaded": self._storage_bytes_uploaded,
                    "bytes_downloaded": self._storage_bytes_downloaded,
                    "errors": self._storage_errors,
                    "fallback_activations": self._storage_fallback_count,
                },
                "system": self.get_system_resource_metrics(),
                "audit": {
                    "total_events_logged": self._audit_events_count,
                },
            }


default_metrics_collector = MetricsCollector()


# ---------------------------------------------------------------------------
# Audit Logger for Security & Critical Actions
# ---------------------------------------------------------------------------

audit_logger = logging.getLogger("audit")


def log_audit_event(
    action: str,
    status: str,
    user_id: Optional[str] = None,
    resource_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """Emit a structured, sanitized security/operational audit log record."""
    default_metrics_collector.record_audit_event()

    safe_details = redact_sensitive_data(details or {})
    audit_data = {
        "audit_event": action,
        "status": status,
        "user_id": user_id or "anonymous",
        "resource_id": resource_id,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "request_id": get_request_id(),
        "correlation_id": get_correlation_id(),
        "details": safe_details,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    audit_logger.info(
        "AUDIT: %s [%s] user=%s resource=%s",
        action,
        status,
        user_id or "anonymous",
        resource_id or "-",
        extra={"audit_data": audit_data},
    )


# ---------------------------------------------------------------------------
# Logging Initialization Helper
# ---------------------------------------------------------------------------


def setup_logging(
    log_level: Optional[str] = None,
    json_logging: Optional[bool] = None,
) -> None:
    """Initialize application-wide logging with structured JSON formatting and redaction filters."""
    level_name = log_level or os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    use_json = json_logging
    if use_json is None:
        raw_json = os.environ.get("JSON_LOGGING", "true").strip().lower()
        use_json = raw_json in ("true", "1", "yes")

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(level)
    stream_handler.addFilter(RedactionFilter())

    if use_json:
        stream_handler.setFormatter(StructuredJsonFormatter())
    else:
        stream_handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(name)s (%(module)s:%(lineno)d): %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    root_logger.addHandler(stream_handler)
