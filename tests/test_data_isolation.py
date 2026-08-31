"""Tests for user data isolation, IDOR prevention, and user-scoped job management."""

import pytest

from app.models import ShortsGenerationRequest, VideoSource, VideoSourceType
from app.services.job_service import JobService
from app.services.job_sqlite import SQLiteJobStore


class TestDataIsolation:
    def test_multi_user_job_isolation(self, tmp_path):
        db_path = str(tmp_path / "test_isolation_jobs.sqlite3")
        store = SQLiteJobStore(db_path=db_path)
        service = JobService(db_path=db_path)

        req_a = ShortsGenerationRequest(
            source=VideoSource(type=VideoSourceType.UPLOAD, location="local_a.mp4"),
            clip_duration_seconds=60.0,
            number_of_clips=2,
            user_id="user-A",
        )
        job_a = service.create_job(req_a, user_id="user-A")

        req_b = ShortsGenerationRequest(
            source=VideoSource(type=VideoSourceType.UPLOAD, location="local_b.mp4"),
            clip_duration_seconds=60.0,
            number_of_clips=2,
            user_id="user-B",
        )
        job_b = service.create_job(req_b, user_id="user-B")

        # User A lists only User A jobs
        jobs_a = service.list_jobs(user_id="user-A")
        assert len(jobs_a) == 1
        assert jobs_a[0].job_id == job_a.job_id

        # User B lists only User B jobs
        jobs_b = service.list_jobs(user_id="user-B")
        assert len(jobs_b) == 1
        assert jobs_b[0].job_id == job_b.job_id

        # IDOR prevention on get_job
        assert service.get_job(job_a.job_id, user_id="user-A") is not None
        assert service.get_job(job_a.job_id, user_id="user-B") is None

        assert service.get_job(job_b.job_id, user_id="user-B") is not None
        assert service.get_job(job_b.job_id, user_id="user-A") is None

        # IDOR prevention on delete_job
        assert service.delete_job(job_a.job_id, user_id="user-B") is False
        assert service.get_job(job_a.job_id, user_id="user-A") is not None

        assert service.delete_job(job_a.job_id, user_id="user-A") is True
        assert service.get_job(job_a.job_id, user_id="user-A") is None


def test_api_user_isolation_and_idor_prevention(tmp_path):
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    # Unique test emails
    email_a = f"alpha_{uuid4().hex[:8]}@example.com"
    email_b = f"beta_{uuid4().hex[:8]}@example.com"

    # Register users via API
    res_reg_a = client.post("/api/auth/register", json={"email": email_a, "password": "Password123!"})
    assert res_reg_a.status_code == 200
    tok_a = res_reg_a.json()["access_token"]
    user_a_id = res_reg_a.json()["user"]["user_id"]

    res_reg_b = client.post("/api/auth/register", json={"email": email_b, "password": "Password123!"})
    assert res_reg_b.status_code == 200
    tok_b = res_reg_b.json()["access_token"]
    user_b_id = res_reg_b.json()["user"]["user_id"]

    headers_a = {"Authorization": f"Bearer {tok_a}"}
    headers_b = {"Authorization": f"Bearer {tok_b}"}

    # Protected me endpoint rejects unauthenticated
    unauth_me = client.get("/api/auth/me")
    assert unauth_me.status_code == 401

    # Protected me endpoint accepts authenticated
    auth_me = client.get("/api/auth/me", headers=headers_a)
    assert auth_me.status_code == 200
    assert auth_me.json()["email"] == email_a

    # User A creates job
    res_job_a = client.post(
        "/api/jobs",
        headers=headers_a,
        json={
            "source": {"type": "upload", "location": "alpha_video.mp4"},
            "clip_duration_seconds": 60,
            "number_of_clips": 1,
        },
    )
    assert res_job_a.status_code == 200
    job_a_id = res_job_a.json()["job_id"]
    assert res_job_a.json()["user_id"] == user_a_id

    # User A can get their own job
    get_a_by_a = client.get(f"/api/jobs/{job_a_id}", headers=headers_a)
    assert get_a_by_a.status_code == 200

    # User B cannot get User A's job (403 Forbidden)
    get_a_by_b = client.get(f"/api/jobs/{job_a_id}", headers=headers_b)
    assert get_a_by_b.status_code == 403

    # Unauthenticated user cannot get User A's job (403 Forbidden)
    get_a_unauth = client.get(f"/api/jobs/{job_a_id}")
    assert get_a_unauth.status_code == 403

    # User B cannot delete User A's job (403 Forbidden)
    del_a_by_b = client.delete(f"/api/jobs/{job_a_id}", headers=headers_b)
    assert del_a_by_b.status_code == 403

    # User A can delete their own job
    del_a_by_a = client.delete(f"/api/jobs/{job_a_id}", headers=headers_a)
    assert del_a_by_a.status_code == 200
