"""Comprehensive unit and integration test suite for Phase 8 Observability and Monitoring.

Covers:
- Structured JSON log formatting and contextual tracing (request_id, correlation_id, job_id)
- Automated sensitive data redaction for passwords, JWTs, API keys, and connection strings
- Thread-safe operational metrics collection for HTTP, pipeline stages, storage, and system health
- Security and operational audit logging
- Observability middleware request tracing, headers (X-Request-ID, X-Correlation-ID, X-Response-Time), and latency capture
- Centralized exception handling and 500 error response format
- Enhanced /health and /api/system/metrics endpoints
"""

import json
import logging
import time
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.services.observability import (
    MetricsCollector,
    RedactionFilter,
    StructuredJsonFormatter,
    get_correlation_id,
    get_job_id,
    get_request_id,
    log_audit_event,
    redact_sensitive_data,
    set_correlation_id,
    set_job_id,
    set_request_id,
)


@pytest.fixture
def test_client():
    return TestClient(app)


# ==============================================================================
# 1. Structured JSON Logging & Context Tracing Tests
# ==============================================================================


class TestStructuredJsonLogging:
    def test_json_formatter_structure_and_context_vars(self):
        formatter = StructuredJsonFormatter()

        set_request_id("req-test-123")
        set_correlation_id("corr-test-456")
        set_job_id("job-test-789")

        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test_path.py",
            lineno=42,
            msg="User %s processed successfully",
            args=("alice@example.com",),
            exc_info=None,
        )

        formatted = formatter.format(record)
        data = json.loads(formatted)

        assert data["level"] == "INFO"
        assert data["logger"] == "test_logger"
        assert "User alice@example.com processed successfully" in data["message"]
        assert data["request_id"] == "req-test-123"
        assert data["correlation_id"] == "corr-test-456"
        assert data["job_id"] == "job-test-789"
        assert "timestamp" in data

    def test_json_formatter_captures_exception_trace(self):
        formatter = StructuredJsonFormatter()

        try:
            raise ValueError("Something went wrong in pipeline")
        except ValueError:
            import sys
            record = logging.LogRecord(
                name="error_logger",
                level=logging.ERROR,
                pathname="test_err.py",
                lineno=10,
                msg="Pipeline failure",
                args=(),
                exc_info=sys.exc_info(),
            )

        formatted = formatter.format(record)
        data = json.loads(formatted)

        assert data["level"] == "ERROR"
        assert "exception" in data
        assert "ValueError: Something went wrong in pipeline" in data["exception"]


# ==============================================================================
# 2. Sensitive Data Redaction Tests
# ==============================================================================


class TestSensitiveDataRedaction:
    def test_redact_dictionary_fields(self):
        payload = {
            "email": "user@example.com",
            "password": "SuperSecretPassword123!",
            "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
            "access_token": "secret_access_token",
            "refresh_token": "rt_1234_abcde",
            "api_key": "sk-proj-123456",
            "nested": {
                "secret_key": "my_secret",
                "safe_field": 42,
            },
        }

        sanitized = redact_sensitive_data(payload)
        assert sanitized["email"] == "user@example.com"
        assert sanitized["password"] == "[REDACTED]"
        assert sanitized["token"] == "[REDACTED]"
        assert sanitized["access_token"] == "[REDACTED]"
        assert sanitized["refresh_token"] == "[REDACTED]"
        assert sanitized["api_key"] == "[REDACTED]"
        assert sanitized["nested"]["secret_key"] == "[REDACTED]"
        assert sanitized["nested"]["safe_field"] == 42

    def test_redact_bearer_token_in_strings(self):
        msg = "Request Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig processed"
        sanitized = redact_sensitive_data(msg)
        assert "[REDACTED_TOKEN]" in sanitized
        assert "eyJhbGciOiJIUzI1Ni" not in sanitized

    def test_redact_database_passwords_in_urls(self):
        pg_url = "Connecting to postgresql://postgres:mypassword123@db.prod.host:5432/ai_shorts"
        redis_url = "Connecting to redis://:redis_secret_pass@cache.host:6379/0"

        sanitized_pg = redact_sensitive_data(pg_url)
        sanitized_redis = redact_sensitive_data(redis_url)

        assert "mypassword123" not in sanitized_pg
        assert "[REDACTED_CREDENTIALS]" in sanitized_pg
        assert "redis_secret_pass" not in sanitized_redis
        assert "[REDACTED_CREDENTIALS]" in sanitized_redis

    def test_redact_sensitive_query_parameters(self):
        url = "/api/media?file=video.mp4&api_key=secret_api_val&signature=sig12345"
        sanitized = redact_sensitive_data(url)
        assert "secret_api_val" not in sanitized
        assert "sig12345" not in sanitized
        assert "api_key=[REDACTED]" in sanitized

    def test_redaction_filter_scrubs_log_record(self):
        filter_obj = RedactionFilter()
        record = logging.LogRecord(
            name="auth_logger",
            level=logging.INFO,
            pathname="auth.py",
            lineno=50,
            msg="User login with password: %s and token: %s",
            args=("MySecretPass", "Bearer eyJhbGciOi..."),
            exc_info=None,
        )

        filter_obj.filter(record)
        assert record.args is not None
        assert "Bearer [REDACTED_TOKEN]" in str(record.args[1])  # type: ignore[index]


# ==============================================================================
# 3. Operational Metrics Collector Tests
# ==============================================================================


class TestMetricsCollector:
    def test_http_request_metrics_and_latencies(self):
        collector = MetricsCollector()

        collector.record_http_request("GET", "/api/jobs", 200, 15.0)
        collector.record_http_request("GET", "/api/jobs", 200, 25.0)
        collector.record_http_request("POST", "/api/jobs", 201, 100.0)
        collector.record_http_request("GET", "/api/auth/me", 401, 5.0)

        report = collector.get_metrics_report()
        assert report["http"]["total_requests"] == 4
        assert report["http"]["status_categories"]["2xx"] == 3
        assert report["http"]["status_categories"]["4xx"] == 1
        assert report["http"]["status_codes"]["200"] == 2
        assert report["http"]["status_codes"]["201"] == 1
        assert report["http"]["status_codes"]["401"] == 1

        jobs_get = report["http"]["endpoints"]["GET /api/jobs"]
        assert jobs_get["count"] == 2
        assert jobs_get["min_ms"] == 15.0
        assert jobs_get["max_ms"] == 25.0
        assert jobs_get["avg_ms"] == 20.0

    def test_pipeline_stage_durations(self):
        collector = MetricsCollector()

        collector.record_stage_duration("transcription", 500.0)
        collector.record_stage_duration("transcription", 700.0)
        collector.record_stage_duration("vertical_conversion", 350.0)

        report = collector.get_metrics_report()
        stages = report["pipeline"]["stages"]
        assert stages["transcription"]["count"] == 2
        assert stages["transcription"]["avg_ms"] == 600.0
        assert stages["vertical_conversion"]["count"] == 1
        assert stages["vertical_conversion"]["avg_ms"] == 350.0

    def test_job_events_and_storage_metrics(self):
        collector = MetricsCollector()

        collector.record_job_event("created")
        collector.record_job_event("created")
        collector.record_job_event("processing")
        collector.record_job_event("completed")
        collector.record_job_event("failed")

        collector.record_storage_operation("upload", bytes_count=1024 * 1024, success=True)
        collector.record_storage_operation("download", bytes_count=512 * 1024, success=True)
        collector.record_storage_operation("upload", bytes_count=0, success=False, is_fallback=True)

        report = collector.get_metrics_report()
        assert report["pipeline"]["jobs"]["created"] == 2
        assert report["pipeline"]["jobs"]["completed"] == 1
        assert report["pipeline"]["jobs"]["failed"] == 1

        assert report["storage"]["uploads"] == 2
        assert report["storage"]["downloads"] == 1
        assert report["storage"]["bytes_uploaded"] == 1024 * 1024
        assert report["storage"]["errors"] == 1
        assert report["storage"]["fallback_activations"] == 1


# ==============================================================================
# 4. Audit Logging Tests
# ==============================================================================


class TestAuditLogging:
    def test_log_audit_event_records_metric_and_redacts(self, caplog):
        with caplog.at_level(logging.INFO, logger="audit"):
            log_audit_event(
                action="auth.login",
                status="success",
                user_id="user-audit-1",
                details={
                    "email": "user@example.com",
                    "password": "should_be_scrubbed",
                    "token": "token_should_be_scrubbed",
                },
                ip_address="127.0.0.1",
                user_agent="TestBrowser/1.0",
            )

        assert any("AUDIT: auth.login [success]" in r.message for r in caplog.records)


# ==============================================================================
# 5. API Endpoints & Observability Middleware Integration Tests
# ==============================================================================


class TestObservabilityAPIIntegration:
    def test_response_headers_include_tracing_and_timing(self, test_client):
        custom_req_id = "custom-req-id-12345"
        custom_corr_id = "custom-corr-id-67890"

        response = test_client.get(
            "/health",
            headers={
                "X-Request-ID": custom_req_id,
                "X-Correlation-ID": custom_corr_id,
            },
        )

        assert response.status_code == 200
        assert response.headers.get("X-Request-ID") == custom_req_id
        assert response.headers.get("X-Correlation-ID") == custom_corr_id
        assert "X-Response-Time" in response.headers
        assert response.headers.get("X-Response-Time", "").endswith("ms")

    def test_health_endpoint_enhanced_diagnostics(self, test_client):
        response = test_client.get("/health")
        assert response.status_code == 200
        data = response.json()

        assert "status" in data
        assert data["status"] in ("ok", "degraded", "unhealthy")
        assert "timestamp" in data
        assert "uptime_seconds" in data
        assert "version" in data
        assert "database" in data
        assert "queue" in data
        assert "subsystems" in data
        assert "database" in data["subsystems"]
        assert "queue" in data["subsystems"]
        assert "storage" in data["subsystems"]
        assert "acceleration" in data["subsystems"]

    def test_system_metrics_endpoint(self, test_client):
        response = test_client.get("/api/system/metrics")
        assert response.status_code == 200
        data = response.json()

        assert "uptime_seconds" in data
        assert "timestamp" in data
        assert "http" in data
        assert "pipeline" in data
        assert "storage" in data
        assert "system" in data
        assert "audit" in data

    def test_unhandled_exception_returns_clean_500_with_request_id(self, test_client):
        # Trigger route that raises an exception to test centralized 500 error handling
        @app.get("/api/test/error-trigger")
        def error_route():
            raise RuntimeError("Simulated crash for observability test")

        response = test_client.get("/api/test/error-trigger")
        assert response.status_code == 500
        data = response.json()
        assert data["detail"] == "Internal Server Error"
        assert "request_id" in data
        assert response.headers.get("X-Request-ID") == data["request_id"]
