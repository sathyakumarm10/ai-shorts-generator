"""Comprehensive unit and integration tests for StorageService, S3/R2 backends, and system diagnostics."""

from io import BytesIO
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import urllib.error
import urllib.request
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.storage_service import (
    LocalStorageService,
    R2StorageService,
    S3StorageService,
    StorageBackend,
    StorageConfig,
    StorageError,
    StorageReport,
    get_storage_report,
    get_storage_service,
)


class TestStorageConfig:
    def test_default_config(self, monkeypatch):
        monkeypatch.delenv("STORAGE_BACKEND", raising=False)
        monkeypatch.delenv("S3_ENDPOINT", raising=False)
        monkeypatch.delenv("S3_BUCKET", raising=False)
        monkeypatch.delenv("S3_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("S3_SECRET_ACCESS_KEY", raising=False)

        config = StorageConfig.from_env()
        assert config.backend == StorageBackend.LOCAL
        assert config.bucket == "ai-shorts-bucket"
        assert config.enable_local_fallback is True
        assert config.max_retries == 3

    def test_s3_config_from_env(self, monkeypatch):
        monkeypatch.setenv("STORAGE_BACKEND", "s3")
        monkeypatch.setenv("S3_ENDPOINT", "https://s3.us-west-2.amazonaws.com")
        monkeypatch.setenv("S3_REGION", "us-west-2")
        monkeypatch.setenv("S3_BUCKET", "prod-shorts-bucket")
        monkeypatch.setenv("S3_ACCESS_KEY_ID", "AKIA12345")
        monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "SECRET12345")
        monkeypatch.setenv("S3_PUBLIC_BASE_URL", "https://cdn.example.com")
        monkeypatch.setenv("STORAGE_MAX_RETRIES", "5")
        monkeypatch.setenv("STORAGE_ENABLE_LOCAL_FALLBACK", "true")

        config = StorageConfig.from_env()
        assert config.backend == StorageBackend.S3
        assert config.endpoint_url == "https://s3.us-west-2.amazonaws.com"
        assert config.region == "us-west-2"
        assert config.bucket == "prod-shorts-bucket"
        assert config.access_key_id == "AKIA12345"
        assert config.secret_access_key == "SECRET12345"
        assert config.public_base_url == "https://cdn.example.com"
        assert config.max_retries == 5
        assert config.enable_local_fallback is True

    def test_r2_config_from_env(self, monkeypatch):
        monkeypatch.setenv("STORAGE_BACKEND", "r2")
        monkeypatch.setenv("R2_ENDPOINT", "https://acc123.r2.cloudflarestorage.com")
        monkeypatch.setenv("R2_BUCKET", "r2-shorts-bucket")
        monkeypatch.setenv("R2_ACCESS_KEY_ID", "R2KEY123")
        monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "R2SECRET123")

        config = StorageConfig.from_env()
        assert config.backend == StorageBackend.R2
        assert config.endpoint_url == "https://acc123.r2.cloudflarestorage.com"
        assert config.region == "auto"
        assert config.bucket == "r2-shorts-bucket"


class TestLocalStorageService:
    def test_local_storage_file_operations(self, tmp_path):
        service = LocalStorageService(root_dir=tmp_path)
        sample = tmp_path / "sample.txt"
        sample.write_text("hello storage")

        stored_path = service.store_file(sample, "jobs/123/sample.txt")
        assert Path(stored_path).is_file()
        assert service.exists("jobs/123/sample.txt") is True

        retrieved = service.get_file_path_or_url("jobs/123/sample.txt")
        assert Path(retrieved).is_file()

        presigned = service.get_presigned_url("jobs/123/sample.txt")
        assert presigned.startswith("/api/media?path=jobs/123/sample.txt")

        # Download file to a new path
        download_dest = tmp_path / "downloaded.txt"
        service.download_file("jobs/123/sample.txt", download_dest)
        assert download_dest.read_text() == "hello storage"

        assert service.delete_file("jobs/123/sample.txt") is True
        assert service.exists("jobs/123/sample.txt") is False

    def test_local_storage_delete_prefix(self, tmp_path):
        service = LocalStorageService(root_dir=tmp_path)
        for i in range(3):
            file_i = tmp_path / f"temp_{i}.txt"
            file_i.write_text(f"content {i}")
            service.store_file(file_i, f"jobs/job_abc/file_{i}.txt")

        assert service.exists("jobs/job_abc/file_0.txt") is True
        deleted_count = service.delete_prefix("jobs/job_abc")
        assert deleted_count == 3
        assert service.exists("jobs/job_abc/file_0.txt") is False

    def test_local_storage_path_traversal_prevention(self, tmp_path):
        service = LocalStorageService(root_dir=tmp_path)
        sample = tmp_path / "sample.txt"
        sample.write_text("hello")

        with pytest.raises(StorageError, match="Path traversal detected"):
            service.store_file(sample, "../../../escaped.txt")

        with pytest.raises(StorageError, match="Path traversal detected"):
            service.get_file_path_or_url("../../escaped.txt")

    def test_local_storage_missing_source_file(self, tmp_path):
        service = LocalStorageService(root_dir=tmp_path)
        missing = tmp_path / "non_existent.txt"
        with pytest.raises(StorageError, match="Source file not found"):
            service.store_file(missing, "dest.txt")


class TestS3StorageService:
    def test_s3_storage_presigned_url_generation(self):
        s3 = S3StorageService(
            endpoint_url="https://s3.us-east-1.amazonaws.com",
            region="us-east-1",
            bucket="my-shorts-bucket",
            access_key_id="AKIAEXAMPLE123",
            secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )
        url = s3.get_file_path_or_url("users/u1/jobs/j1/clip.mp4", expires_in_seconds=3600)
        assert "https://s3.us-east-1.amazonaws.com/my-shorts-bucket/users/u1/jobs/j1/clip.mp4" in url
        assert "X-Amz-Signature=" in url
        assert "X-Amz-Credential=" in url
        assert "X-Amz-Algorithm=AWS4-HMAC-SHA256" in url

    def test_s3_public_base_url_presigned_url(self):
        s3 = S3StorageService(
            endpoint_url="https://s3.us-east-1.amazonaws.com",
            bucket="my-shorts-bucket",
            public_base_url="https://cdn.myshorts.app",
        )
        url = s3.get_presigned_url("jobs/j1/final.mp4")
        assert url == "https://cdn.myshorts.app/jobs/j1/final.mp4"

    def test_s3_sigv4_headers_generation(self):
        s3 = S3StorageService(
            endpoint_url="https://s3.us-east-1.amazonaws.com",
            region="us-east-1",
            bucket="test-bucket",
            access_key_id="TESTKEY",
            secret_access_key="TESTSECRET",
        )
        url, headers = s3._generate_sigv4_headers(
            method="PUT",
            clean_key="jobs/1/video.mp4",
            payload_bytes=b"sample video bytes",
            content_type="video/mp4",
        )
        assert url.startswith("https://s3.us-east-1.amazonaws.com/test-bucket/jobs/1/video.mp4")
        assert "Authorization" in headers
        assert "AWS4-HMAC-SHA256" in headers["Authorization"]
        assert "x-amz-content-sha256" in headers
        assert headers["Content-Type"] == "video/mp4"

    def test_s3_upload_file_successful_http(self, tmp_path, monkeypatch):
        s3 = S3StorageService(
            endpoint_url="https://s3.us-east-1.amazonaws.com",
            region="us-east-1",
            bucket="test-bucket",
            access_key_id="TESTKEY",
            secret_access_key="TESTSECRET",
            local_fallback=LocalStorageService(root_dir=tmp_path / "local"),
        )
        video_file = tmp_path / "clip.mp4"
        video_file.write_bytes(b"fake mp4 video bytes")

        # Mock urllib.request.urlopen to return successful 200 response
        mock_resp = MagicMock()
        mock_resp.read.return_value = b""
        mock_resp.__enter__.return_value = mock_resp

        mock_urlopen = MagicMock(return_value=mock_resp)
        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        result_url = s3.upload_file(video_file, "jobs/100/clip.mp4")
        assert "jobs/100/clip.mp4" in result_url
        assert mock_urlopen.called

    def test_s3_upload_with_retry_on_transient_error(self, monkeypatch):
        s3 = S3StorageService(
            endpoint_url="https://s3.us-east-1.amazonaws.com",
            region="us-east-1",
            bucket="test-bucket",
            access_key_id="TESTKEY",
            secret_access_key="TESTSECRET",
            config=StorageConfig(max_retries=3),
        )

        import email.message

        attempts = 0

        def fake_urlopen(req, timeout=15):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                # Raise 503 Service Unavailable
                hdrs = email.message.Message()
                raise urllib.error.HTTPError(req.full_url, 503, "Service Unavailable", hdrs, BytesIO(b""))
            # Succeed on 3rd attempt
            mock_resp = MagicMock()
            mock_resp.read.return_value = b"success"
            mock_resp.__enter__.return_value = mock_resp
            return mock_resp

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr("time.sleep", lambda s: None)

        data = s3._execute_http_with_retry(
            url="https://s3.us-east-1.amazonaws.com/test-bucket/test.txt",
            method="GET",
            headers={"Host": "s3.us-east-1.amazonaws.com"},
        )
        assert data == b"success"
        assert attempts == 3

    def test_s3_upload_fallback_to_local_on_failure(self, tmp_path, monkeypatch):
        local_dir = tmp_path / "fallback_outputs"
        s3 = S3StorageService(
            endpoint_url="https://s3.us-east-1.amazonaws.com",
            region="us-east-1",
            bucket="test-bucket",
            access_key_id="TESTKEY",
            secret_access_key="TESTSECRET",
            config=StorageConfig(enable_local_fallback=True, max_retries=1, local_root_dir=local_dir),
            local_fallback=LocalStorageService(root_dir=local_dir),
        )
        video_file = tmp_path / "fallback_clip.mp4"
        video_file.write_bytes(b"fallback video content")

        # Simulate network error
        def fail_urlopen(req, timeout=15):
            raise urllib.error.URLError("Connection refused")

        monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)

        stored_ref = s3.upload_file(video_file, "jobs/999/fallback_clip.mp4")
        # Should have fallen back and stored locally
        assert (local_dir / "jobs" / "999" / "fallback_clip.mp4").is_file()
        assert stored_ref.endswith("fallback_clip.mp4")


class TestR2StorageService:
    def test_r2_storage_configuration(self):
        r2 = R2StorageService(
            endpoint_url="https://cf_account_123.r2.cloudflarestorage.com",
            bucket="shorts-r2-bucket",
            access_key_id="R2KEY",
            secret_access_key="R2SECRET",
        )
        assert r2.config.backend == StorageBackend.R2
        assert r2.region == "auto"

        url = r2.get_presigned_url("jobs/j2/output.mp4")
        assert "https://cf_account_123.r2.cloudflarestorage.com/shorts-r2-bucket/jobs/j2/output.mp4" in url
        assert "X-Amz-Signature=" in url
        assert "X-Amz-Credential=R2KEY" in url


class TestStorageDiagnosticsAndAPI:
    def test_storage_report(self):
        config = StorageConfig(
            backend=StorageBackend.S3,
            endpoint_url="https://s3.us-east-1.amazonaws.com",
            bucket="diag-bucket",
            region="us-east-1",
            access_key_id="KEY",
            secret_access_key="SECRET",
        )
        service = S3StorageService(config=config)
        report = get_storage_report(service)

        assert isinstance(report, StorageReport)
        assert report.configured_backend == "s3"
        assert report.bucket == "diag-bucket"
        assert report.is_cloud_active is True
        assert report.local_fallback_enabled is True

    def test_api_system_storage_endpoint(self):
        client = TestClient(app)
        response = client.get("/api/system/storage")
        assert response.status_code == 200
        data = response.json()
        assert "backend" in data
        assert "configured_backend" in data
        assert "bucket" in data
        assert "is_cloud_active" in data
        assert "local_fallback_enabled" in data
