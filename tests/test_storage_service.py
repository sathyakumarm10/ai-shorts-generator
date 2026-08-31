"""Tests for LocalStorageService and S3StorageService with signed URL generation."""

from pathlib import Path
import pytest

from app.services.storage_service import (
    LocalStorageService,
    S3StorageService,
    StorageError,
)


class TestStorageService:
    def test_local_storage_file_operations(self, tmp_path):
        service = LocalStorageService(root_dir=tmp_path)
        sample = tmp_path / "sample.txt"
        sample.write_text("hello storage")

        stored_path = service.store_file(sample, "jobs/123/sample.txt")
        assert Path(stored_path).is_file()
        assert service.exists("jobs/123/sample.txt") is True

        retrieved = service.get_file_path_or_url("jobs/123/sample.txt")
        assert Path(retrieved).is_file()

        assert service.delete_file("jobs/123/sample.txt") is True
        assert service.exists("jobs/123/sample.txt") is False

    def test_local_storage_path_traversal_prevention(self, tmp_path):
        service = LocalStorageService(root_dir=tmp_path)
        sample = tmp_path / "sample.txt"
        sample.write_text("hello")

        with pytest.raises(StorageError):
            service.store_file(sample, "../../../escaped.txt")

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
