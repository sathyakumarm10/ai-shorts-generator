"""Unit and integration tests for MediaStorageService and the /api/media streaming endpoint."""

from pathlib import Path
import io
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app
from app.services.job_service import JobService
from app.services.media_storage_service import (
    DEFAULT_MEDIA_ROOT,
    MediaStorageError,
    MediaStorageService,
)

# ---------------------------------------------------------------------------
# Unit tests for MediaStorageService
# ---------------------------------------------------------------------------

class TestMediaStorageService:
    def test_job_dir_creation(self, tmp_path):
        service = MediaStorageService(media_root=tmp_path)
        job_dir = service.get_job_dir("job_123")

        assert job_dir.is_dir()
        assert job_dir == tmp_path / "jobs" / "job_123"

    def test_job_subdir_creation(self, tmp_path):
        service = MediaStorageService(media_root=tmp_path)
        clips_dir = service.get_job_subdir("job_123", MediaStorageService.CLIPS_SUBDIR)
        vertical_dir = service.get_job_subdir("job_123", MediaStorageService.VERTICAL_SUBDIR)
        captioned_dir = service.get_job_subdir("job_123", MediaStorageService.CAPTIONED_SUBDIR)

        assert clips_dir.is_dir()
        assert vertical_dir.is_dir()
        assert captioned_dir.is_dir()
        assert clips_dir.parent == tmp_path / "jobs" / "job_123"

    def test_copy_to_job_dir(self, tmp_path):
        service = MediaStorageService(media_root=tmp_path)
        src_file = tmp_path / "sample.mp4"
        src_file.write_bytes(b"dummy mp4 video bytes")

        copied = service.copy_to_job_dir(
            source_path=src_file,
            job_id="job_abc",
            subdir=MediaStorageService.SOURCE_SUBDIR,
            filename="source_video.mp4",
        )

        assert copied.is_file()
        assert copied.name == "source_video.mp4"
        assert copied.read_bytes() == b"dummy mp4 video bytes"
        assert copied.parent == tmp_path / "jobs" / "job_abc" / "source"

    def test_resolve_media_path_relative_and_absolute(self, tmp_path):
        service = MediaStorageService(media_root=tmp_path)
        dest = service.get_job_subdir("job_abc", "captioned") / "final.mp4"
        dest.write_bytes(b"final short")

        # Relative resolution
        rel_resolved = service.resolve_media_path("jobs/job_abc/captioned/final.mp4")
        assert rel_resolved == dest.resolve()

        # Absolute resolution
        abs_resolved = service.resolve_media_path(dest.resolve())
        assert abs_resolved == dest.resolve()

    def test_resolve_media_path_traversal_rejected(self, tmp_path):
        service = MediaStorageService(media_root=tmp_path)
        with pytest.raises(MediaStorageError):
            service.resolve_media_path("../outside.mp4")

    def test_to_relative_path_and_media_url(self, tmp_path):
        service = MediaStorageService(media_root=tmp_path)
        dest = service.get_job_subdir("job_abc", "captioned") / "final.mp4"
        dest.write_bytes(b"data")

        rel_path = service.to_relative_path(dest)
        assert rel_path == "jobs/job_abc/captioned/final.mp4"

        url = service.to_media_url(dest)
        assert url == "/api/media?path=jobs/job_abc/captioned/final.mp4"

    def test_invalid_job_id_raises_error(self, tmp_path):
        service = MediaStorageService(media_root=tmp_path)
        with pytest.raises(MediaStorageError):
            service.get_job_dir("../escaped")
        with pytest.raises(MediaStorageError):
            service.get_job_dir("job/with/slash")


# ---------------------------------------------------------------------------
# Integration tests for /api/media serving
# ---------------------------------------------------------------------------

@pytest.fixture
def media_api(monkeypatch, tmp_path):
    job_service = JobService()
    media_storage = MediaStorageService(media_root=tmp_path / "outputs")
    monkeypatch.setattr(main_module, "default_job_service", job_service)
    monkeypatch.setattr(main_module, "default_media_storage", media_storage)
    monkeypatch.setattr(main_module.default_job_runner, "submit_job", lambda *args, **kwargs: None)
    return job_service, media_storage


def _job_payload():
    return {
        "source": {"type": "youtube", "location": "https://www.youtube.com/watch?v=example"},
        "clip_duration_seconds": 30,
        "number_of_clips": 1,
    }


def _register(client: TestClient, prefix: str) -> str:
    response = client.post(
        "/api/auth/register",
        json={
            "email": f"{prefix}-{uuid4().hex}@example.com",
            "password": "Password123!",
        },
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _write_job_media(media_storage: MediaStorageService, job_id: str, name: str = "short_1.mp4") -> Path:
    output = media_storage.get_job_subdir(job_id, "captioned") / name
    output.write_bytes(b"captioned vertical short bytes")
    return output


def test_media_owner_can_access_without_bearer_header(media_api):
    _, media_storage = media_api
    owner_client = TestClient(app)
    token = _register(owner_client, "media-owner")
    created = owner_client.post(
        "/api/jobs",
        json=_job_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert created.status_code == 200
    media_file = _write_job_media(media_storage, created.json()["job_id"])

    response = owner_client.get("/api/media", params={"file_path": str(media_file)})

    assert response.status_code == 200
    assert response.content == b"captioned vertical short bytes"
    assert "video/mp4" in response.headers.get("content-type", "")


def test_another_authenticated_user_cannot_access_media(media_api):
    _, media_storage = media_api
    owner_client = TestClient(app)
    other_client = TestClient(app)
    owner_token = _register(owner_client, "media-owner")
    other_token = _register(other_client, "media-other")
    created = owner_client.post(
        "/api/jobs",
        json=_job_payload(),
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    media_file = _write_job_media(media_storage, created.json()["job_id"])

    response = other_client.get(
        "/api/media",
        params={"file_path": str(media_file)},
        headers={"Authorization": f"Bearer {other_token}"},
    )

    assert response.status_code == 403


def test_anonymous_media_is_scoped_to_creating_browser_session(media_api):
    _, media_storage = media_api
    owner_client = TestClient(app)
    other_client = TestClient(app)
    created = owner_client.post("/api/jobs", json=_job_payload())
    assert created.status_code == 200
    assert created.json()["user_id"].startswith("anonymous:")
    media_file = _write_job_media(media_storage, created.json()["job_id"])

    assert owner_client.get("/api/media", params={"file_path": str(media_file)}).status_code == 200
    assert other_client.get("/api/media", params={"file_path": str(media_file)}).status_code == 403


def test_get_media_nonexistent_job_file_returns_404(media_api):
    _, media_storage = media_api
    client = TestClient(app)
    created = client.post("/api/jobs", json=_job_payload())
    missing = media_storage.get_job_subdir(created.json()["job_id"], "captioned") / "missing.mp4"

    response = client.get("/api/media", params={"file_path": str(missing)})

    assert response.status_code == 404


def test_get_media_missing_param_returns_400(media_api):
    res = TestClient(app).get("/api/media")
    assert res.status_code == 400


def test_get_media_traversal_outside_approved_rejected(media_api):
    outside_file = Path("backend") / "app" / "main.py"
    res = TestClient(app).get(f"/api/media?file_path={outside_file.resolve()}")
    assert res.status_code == 403


def test_get_media_relative_traversal_rejected(media_api):
    res = TestClient(app).get("/api/media?path=../../backend/app/main.py")
    assert res.status_code in (403, 404)
