"""Tests for POST /api/upload and GET /api/media endpoints."""

from pathlib import Path
import tempfile
import io
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.media_asset_service import default_media_asset_service

client = TestClient(app)


def test_upload_video_valid_mp4(tmp_path):
    file_content = b"fake video content header"
    files = {"file": ("my_sample.mp4", io.BytesIO(file_content), "video/mp4")}

    response = client.post("/api/upload", files=files)
    assert response.status_code == 200
    body = response.json()

    assert "asset_id" in body
    assert "file_path" not in body
    assert body["filename"] == "my_sample.mp4"
    assert body["file_size_bytes"] == len(file_content)

    asset = default_media_asset_service.get_asset(body["asset_id"])
    assert asset is not None
    uploaded_path = Path(asset.stored_path)
    assert uploaded_path.is_file()


def test_upload_video_unsupported_extension_rejected():
    files = {"file": ("malicious.exe", io.BytesIO(b"malware"), "application/octet-stream")}
    response = client.post("/api/upload", files=files)
    assert response.status_code == 400
    assert "Unsupported file format" in response.json()["detail"]


def test_upload_video_empty_file_rejected():
    files = {"file": ("empty.mp4", io.BytesIO(b""), "video/mp4")}
    response = client.post("/api/upload", files=files)
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_get_media_valid_file_in_downloads():
    upload = client.post(
        "/api/upload",
        files={"file": ("valid_sample.mp4", io.BytesIO(b"sample video bytes"), "video/mp4")},
    )
    assert upload.status_code == 200

    asset = default_media_asset_service.get_asset(upload.json()["asset_id"])
    assert asset is not None
    response = client.get("/api/media", params={"file_path": asset.stored_path})
    assert response.status_code == 200
    assert response.content == b"sample video bytes"
    assert "video/mp4" in response.headers.get("content-type", "")


def test_get_media_nonexistent_returns_404():
    response = client.get("/api/media?file_path=downloads/nonexistent_file.mp4")
    assert response.status_code == 404


def test_get_media_forbidden_extension_returns_403(tmp_path):
    download_dir = Path("downloads")
    download_dir.mkdir(parents=True, exist_ok=True)
    source_file = download_dir / "secret.env"
    source_file.write_bytes(b"SECRET_KEY=123")

    response = client.get(f"/api/media?file_path={source_file.resolve()}")
    assert response.status_code == 403


def test_get_media_path_traversal_outside_approved_dir_returns_403(tmp_path):
    outside_dir = Path("backend") / "app"
    outside_file = outside_dir / "main.py"

    response = client.get(f"/api/media?file_path={outside_file.resolve()}")
    assert response.status_code == 403
