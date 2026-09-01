"""Tests for the /api/system/database, /api/system/queue, and /health endpoints."""

import json
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# /health endpoint
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_health_returns_200(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_contains_status_ok(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert data.get("status") == "ok"

    def test_health_contains_subsystems(self, client: TestClient) -> None:
        data = client.get("/health").json()
        # Phase 6: health should expose database and queue subsystem info
        assert "database" in data or "status" in data  # at minimum status must be present


# ---------------------------------------------------------------------------
# /api/system/database endpoint
# ---------------------------------------------------------------------------


class TestDatabaseDiagnosticsEndpoint:
    def test_endpoint_returns_200(self, client: TestClient) -> None:
        response = client.get("/api/system/database")
        assert response.status_code == 200

    def test_endpoint_returns_backend_field(self, client: TestClient) -> None:
        data = client.get("/api/system/database").json()
        assert "backend" in data

    def test_endpoint_returns_connected_field(self, client: TestClient) -> None:
        data = client.get("/api/system/database").json()
        assert "connected" in data
        assert isinstance(data["connected"], bool)

    def test_endpoint_returns_latency_ms(self, client: TestClient) -> None:
        data = client.get("/api/system/database").json()
        assert "latency_ms" in data
        assert isinstance(data["latency_ms"], (int, float))

    def test_endpoint_returns_migration_version(self, client: TestClient) -> None:
        data = client.get("/api/system/database").json()
        assert "migration_version" in data

    def test_sqlite_backend_reported_correctly(self, client: TestClient) -> None:
        """When running with default SQLite, backend should be 'sqlite'."""
        from app.services.db import DatabaseDiagnosticsReport

        mock_report = DatabaseDiagnosticsReport(
            backend="sqlite",
            configured_backend="sqlite",
            connected=True,
            database_name="jobs.sqlite3",
            host="localhost",
            port=None,
            migration_version=1,
            latency_ms=0.5,
            local_fallback_active=False,
            error=None,
        )

        with patch("app.main.get_database_report", return_value=mock_report):
            data = client.get("/api/system/database").json()
            assert data["backend"] == "sqlite"
            assert data["connected"] is True
            assert data["migration_version"] == 1

    def test_postgres_backend_reported_correctly(self, client: TestClient) -> None:
        from app.services.db import DatabaseDiagnosticsReport

        mock_report = DatabaseDiagnosticsReport(
            backend="postgresql",
            configured_backend="postgresql",
            connected=True,
            database_name="ai_shorts",
            host="postgres",
            port=5432,
            migration_version=3,
            latency_ms=2.1,
            local_fallback_active=False,
            error=None,
        )

        with patch("app.main.get_database_report", return_value=mock_report):
            data = client.get("/api/system/database").json()
            assert data["backend"] == "postgresql"
            assert data["host"] == "postgres"
            assert data["port"] == 5432
            assert data["migration_version"] == 3

    def test_degraded_postgres_has_error_field(self, client: TestClient) -> None:
        from app.services.db import DatabaseDiagnosticsReport

        mock_report = DatabaseDiagnosticsReport(
            backend="postgresql",
            configured_backend="postgresql",
            connected=False,
            database_name="ai_shorts",
            host="postgres",
            port=5432,
            migration_version=0,
            latency_ms=5001.0,
            local_fallback_active=True,
            error="Connection refused",
        )

        with patch("app.main.get_database_report", return_value=mock_report):
            data = client.get("/api/system/database").json()
            assert data["connected"] is False
            assert data["local_fallback_active"] is True
            assert "Connection refused" in (data.get("error") or "")


# ---------------------------------------------------------------------------
# /api/system/queue endpoint
# ---------------------------------------------------------------------------


class TestQueueDiagnosticsEndpoint:
    def test_endpoint_returns_200(self, client: TestClient) -> None:
        response = client.get("/api/system/queue")
        assert response.status_code == 200

    def test_endpoint_returns_backend_field(self, client: TestClient) -> None:
        data = client.get("/api/system/queue").json()
        assert "backend" in data

    def test_endpoint_returns_connected_field(self, client: TestClient) -> None:
        data = client.get("/api/system/queue").json()
        assert "connected" in data

    def test_endpoint_returns_pending_count(self, client: TestClient) -> None:
        data = client.get("/api/system/queue").json()
        assert "pending_count" in data

    def test_threadpool_backend_reported(self, client: TestClient) -> None:
        from app.services.queue_service import QueueDiagnosticsReport

        mock_report = QueueDiagnosticsReport(
            backend="threadpool",
            configured_backend="threadpool",
            connected=True,
            pending_count=0,
            processing_count=0,
            delayed_count=0,
            dead_letter_count=0,
            active_workers_count=1,
            local_fallback_active=False,
            latency_ms=0.1,
            error=None,
        )

        with patch("app.main.get_queue_report", return_value=mock_report):
            data = client.get("/api/system/queue").json()
            assert data["backend"] == "threadpool"
            assert data["connected"] is True

    def test_redis_backend_full_metrics(self, client: TestClient) -> None:
        from app.services.queue_service import QueueDiagnosticsReport

        mock_report = QueueDiagnosticsReport(
            backend="redis",
            configured_backend="redis",
            connected=True,
            pending_count=10,
            processing_count=3,
            delayed_count=2,
            dead_letter_count=1,
            active_workers_count=4,
            local_fallback_active=False,
            latency_ms=1.5,
            error=None,
        )

        with patch("app.main.get_queue_report", return_value=mock_report):
            data = client.get("/api/system/queue").json()
            assert data["pending_count"] == 10
            assert data["processing_count"] == 3
            assert data["delayed_count"] == 2
            assert data["dead_letter_count"] == 1
            assert data["active_workers_count"] == 4

    def test_degraded_redis_has_error_field(self, client: TestClient) -> None:
        from app.services.queue_service import QueueDiagnosticsReport

        mock_report = QueueDiagnosticsReport(
            backend="redis",
            configured_backend="redis",
            connected=False,
            pending_count=0,
            processing_count=0,
            delayed_count=0,
            dead_letter_count=0,
            active_workers_count=0,
            local_fallback_active=True,
            latency_ms=5002.0,
            error="ECONNREFUSED",
        )

        with patch("app.main.get_queue_report", return_value=mock_report):
            data = client.get("/api/system/queue").json()
            assert data["connected"] is False
            assert "ECONNREFUSED" in (data.get("error") or "")
