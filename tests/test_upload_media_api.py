"""Tests for POST /api/upload and GET /api/media endpoints."""

from pathlib import Path
import tempfile
import io
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_upload_video_valid_mp4(tmp_path):
    file_content = b"fake video content header"
    files = {"file": ("my_sample.mp4", io.BytesIO(file_content), "video/mp4")}

    response = client.post("/api/upload", files=files)
    assert response.status_code == 200
    body = response.json()

    assert "file_path" in body
    assert body["filename"] == "my_sample.mp4"
    assert body["file_size_bytes"] == len(file_content)

    uploaded_path = Path(body["file_path"])
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
    download_dir = Path("downloads") / "test_media"
    download_dir.mkdir(parents=True, exist_ok=True)
    sample_file = download_dir / "valid_sample.mp4"
    sample_file.write_bytes(b"sample video bytes")

    response = client.get(f"/api/media?file_path={sample_file.resolve()}")
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
