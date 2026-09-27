"""Focused security tests for uploaded source assets and job ownership."""

from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

import app.main as main_module
from app.main import app
from app.services.job_service import JobService
from app.services.media_asset_service import (
    MediaAssetService,
    SQLiteMediaAssetStore,
)


@pytest.fixture
def asset_api(monkeypatch, tmp_path):
    upload_root = tmp_path / "uploads"
    asset_service = MediaAssetService(
        store=SQLiteMediaAssetStore(),
        upload_root=upload_root,
    )
    monkeypatch.setattr(main_module, "UPLOAD_DIR", upload_root)
    monkeypatch.setattr(main_module, "default_media_asset_service", asset_service)
    monkeypatch.setattr(main_module, "default_job_service", JobService())
    monkeypatch.setattr(main_module.default_job_runner, "submit_job", lambda *args, **kwargs: None)
    return asset_service, upload_root


def _register(client: TestClient, prefix: str) -> dict:
    response = client.post(
        "/api/auth/register",
        json={
            "email": f"{prefix}-{uuid4().hex}@example.com",
            "password": "Password123!",
        },
    )
    assert response.status_code == 200
    return response.json()


def _upload(client: TestClient, content: bytes = b"video", headers=None, filename="source.mp4"):
    return client.post(
        "/api/upload",
        files={"file": (filename, BytesIO(content), "video/mp4")},
        headers=headers or {},
    )


def _job_payload(asset_id: str):
    return {
        "source": {"type": "upload", "asset_id": asset_id},
        "clip_duration_seconds": 30,
        "number_of_clips": 1,
    }


def test_valid_upload_returns_opaque_asset_without_local_path(asset_api):
    asset_service, upload_root = asset_api
    client = TestClient(app)

    response = _upload(client, filename="../../unsafe name.mp4")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"asset_id", "filename", "file_size_bytes", "created_at"}
    assert "file_path" not in body
    assert body["filename"] == "unsafe name.mp4"
    asset = asset_service.get_asset(body["asset_id"])
    assert asset is not None
    stored_path = Path(asset.stored_path)
    assert stored_path.is_file()
    assert stored_path.name.startswith("asset_")
    assert stored_path.suffix == ".mp4"
    assert stored_path.is_relative_to(upload_root.resolve())


def test_upload_rejects_empty_and_unsupported_files(asset_api):
    client = TestClient(app)

    empty = _upload(client, content=b"")
    unsupported = client.post(
        "/api/upload",
        files={"file": ("payload.exe", BytesIO(b"data"), "application/octet-stream")},
    )

    assert empty.status_code == 400
    assert unsupported.status_code == 400


def test_oversized_upload_is_rejected_and_partial_file_removed(asset_api, monkeypatch):
    _, upload_root = asset_api
    monkeypatch.setenv("MAX_UPLOAD_SIZE_BYTES", "4")

    response = _upload(TestClient(app), content=b"12345")

    assert response.status_code == 413
    assert not list(upload_root.rglob("*.*"))


def test_asset_registration_failure_removes_completed_upload(asset_api, monkeypatch):
    asset_service, upload_root = asset_api
    monkeypatch.setattr(asset_service, "create_asset", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("db down")))

    response = _upload(TestClient(app), content=b"complete video")

    assert response.status_code == 500
    assert not list(upload_root.rglob("*.*"))


def test_authenticated_owner_may_create_job_with_asset(asset_api):
    client = TestClient(app)
    auth = _register(client, "asset-owner")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    upload = _upload(client, headers=headers)

    response = client.post("/api/jobs", json=_job_payload(upload.json()["asset_id"]), headers=headers)

    assert response.status_code == 200
    assert response.json()["source"]["asset_id"] == upload.json()["asset_id"]
    assert response.json()["source"]["location"] is None


def test_different_authenticated_user_cannot_process_asset(asset_api):
    owner = TestClient(app)
    other = TestClient(app)
    owner_auth = _register(owner, "asset-owner")
    other_auth = _register(other, "asset-other")
    upload = _upload(owner, headers={"Authorization": f"Bearer {owner_auth['access_token']}"})

    response = other.post(
        "/api/jobs",
        json=_job_payload(upload.json()["asset_id"]),
        headers={"Authorization": f"Bearer {other_auth['access_token']}"},
    )

    assert response.status_code == 403


def test_different_anonymous_session_cannot_process_asset(asset_api):
    owner = TestClient(app)
    other = TestClient(app)
    upload = _upload(owner)

    assert owner.post("/api/jobs", json=_job_payload(upload.json()["asset_id"])).status_code == 200
    assert other.post("/api/jobs", json=_job_payload(upload.json()["asset_id"])).status_code == 403


@pytest.mark.parametrize("client_kind", ["anonymous", "authenticated"])
def test_public_job_api_rejects_arbitrary_local_paths(asset_api, client_kind):
    client = TestClient(app)
    headers = {}
    if client_kind == "authenticated":
        auth = _register(client, "path-reject")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

    response = client.post(
        "/api/jobs",
        json={
            "source": {"type": "upload", "location": "C:/server/private/video.mp4"},
            "clip_duration_seconds": 30,
            "number_of_clips": 1,
        },
        headers=headers,
    )

    assert response.status_code == 422


def test_traversal_and_nonexistent_asset_ids_are_rejected(asset_api):
    client = TestClient(app)

    traversal = client.post("/api/jobs", json=_job_payload("../../private/video.mp4"))
    missing = client.post("/api/jobs", json=_job_payload("A" * 43))

    assert traversal.status_code == 422
    assert missing.status_code == 404


def test_url_job_flow_remains_supported(asset_api):
    response = TestClient(app).post(
        "/api/jobs",
        json={
            "source": {"type": "youtube", "location": "https://www.youtube.com/watch?v=example"},
            "clip_duration_seconds": 30,
            "number_of_clips": 1,
        },
    )

    assert response.status_code == 200
