"""Tests for user data isolation, IDOR prevention, and user-scoped job management."""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.models import ShortsGenerationRequest, VideoSource, VideoSourceType
from app.services.job_service import JobService


class TestDataIsolation:
    def test_multi_user_job_isolation(self, tmp_path):
        db_path = str(tmp_path / "test_isolation_jobs.sqlite3")

        service = JobService(db_path=db_path)

        # -------------------------
        # Create User A job
        # -------------------------
        req_a = ShortsGenerationRequest(
            source=VideoSource(
                type=VideoSourceType.UPLOAD,
                location="local_a.mp4",
            ),
            clip_duration_seconds=60.0,
            number_of_clips=2,
            user_id="user-A",
        )

        job_a = service.create_job(
            req_a,
            user_id="user-A",
        )

        # -------------------------
        # Create User B job
        # -------------------------
        req_b = ShortsGenerationRequest(
            source=VideoSource(
                type=VideoSourceType.UPLOAD,
                location="local_b.mp4",
            ),
            clip_duration_seconds=60.0,
            number_of_clips=2,
            user_id="user-B",
        )

        job_b = service.create_job(
            req_b,
            user_id="user-B",
        )

        # -------------------------
        # User A sees only A jobs
        # -------------------------
        jobs_a = service.list_jobs(user_id="user-A")

        assert len(jobs_a) == 1
        assert jobs_a[0].job_id == job_a.job_id
        assert jobs_a[0].user_id == "user-A"

        # -------------------------
        # User B sees only B jobs
        # -------------------------
        jobs_b = service.list_jobs(user_id="user-B")

        assert len(jobs_b) == 1
        assert jobs_b[0].job_id == job_b.job_id
        assert jobs_b[0].user_id == "user-B"

        # -------------------------
        # User A can access A
        # -------------------------
        assert (
            service.get_job(
                job_a.job_id,
                user_id="user-A",
            )
            is not None
        )

        # -------------------------
        # User B cannot access A
        # -------------------------
        assert (
            service.get_job(
                job_a.job_id,
                user_id="user-B",
            )
            is None
        )

        # -------------------------
        # User B can access B
        # -------------------------
        assert (
            service.get_job(
                job_b.job_id,
                user_id="user-B",
            )
            is not None
        )

        # -------------------------
        # User A cannot access B
        # -------------------------
        assert (
            service.get_job(
                job_b.job_id,
                user_id="user-A",
            )
            is None
        )

        # -------------------------
        # User B cannot delete A
        # -------------------------
        assert (
            service.delete_job(
                job_a.job_id,
                user_id="user-B",
            )
            is False
        )

        # A's job must still exist
        assert (
            service.get_job(
                job_a.job_id,
                user_id="user-A",
            )
            is not None
        )

        # -------------------------
        # User A can delete A
        # -------------------------
        assert (
            service.delete_job(
                job_a.job_id,
                user_id="user-A",
            )
            is True
        )

        # A's job is now gone
        assert (
            service.get_job(
                job_a.job_id,
                user_id="user-A",
            )
            is None
        )

        # B's job is unaffected
        assert (
            service.get_job(
                job_b.job_id,
                user_id="user-B",
            )
            is not None
        )


def _register_user(client: TestClient, prefix: str):
    """Register a unique test user and return the response data."""

    email = f"{prefix}_{uuid4().hex}@example.com"

    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "Password123!",
        },
    )

    assert response.status_code == 200, response.text

    data = response.json()

    assert "access_token" in data
    assert "user" in data
    assert "user_id" in data["user"]

    return data


def test_api_user_isolation_and_idor_prevention():
    client = TestClient(app)

    # =========================================================
    # Register User A
    # =========================================================

    user_a = _register_user(
        client,
        "alpha",
    )

    token_a = user_a["access_token"]
    user_a_id = user_a["user"]["user_id"]
    email_a = user_a["user"]["email"]

    headers_a = {
        "Authorization": f"Bearer {token_a}",
    }

    # =========================================================
    # Register User B
    # =========================================================

    user_b = _register_user(
        client,
        "beta",
    )

    token_b = user_b["access_token"]
    user_b_id = user_b["user"]["user_id"]

    headers_b = {
        "Authorization": f"Bearer {token_b}",
    }

    assert user_a_id != user_b_id

    # =========================================================
    # Authentication checks
    # =========================================================

    unauth_me = client.get("/api/auth/me")

    assert unauth_me.status_code == 401

    auth_me = client.get(
        "/api/auth/me",
        headers=headers_a,
    )

    assert auth_me.status_code == 200
    assert auth_me.json()["email"] == email_a
    assert auth_me.json()["user_id"] == user_a_id

    # =========================================================
    # User A creates a job
    # =========================================================

    create_response = client.post(
        "/api/jobs",
        headers=headers_a,
        json={
            "source": {
                "type": "upload",
                "location": "alpha_video.mp4",
            },
            "clip_duration_seconds": 60,
            "number_of_clips": 1,
        },
    )

    assert create_response.status_code == 200, create_response.text

    job_a = create_response.json()

    job_a_id = job_a["job_id"]

    assert job_a["user_id"] == user_a_id

    # =========================================================
    # User A can access their own job
    # =========================================================

    get_a_by_a = client.get(
        f"/api/jobs/{job_a_id}",
        headers=headers_a,
    )

    assert get_a_by_a.status_code == 200

    returned_job = get_a_by_a.json()

    assert returned_job["job_id"] == job_a_id
    assert returned_job["user_id"] == user_a_id

    # =========================================================
    # User B cannot access User A's job
    # =========================================================

    get_a_by_b = client.get(
        f"/api/jobs/{job_a_id}",
        headers=headers_b,
    )

    assert get_a_by_b.status_code == 403

    # =========================================================
    # Unauthenticated user cannot access the job
    # =========================================================

    get_a_unauthenticated = client.get(
        f"/api/jobs/{job_a_id}",
    )

    assert get_a_unauthenticated.status_code == 403


    # =========================================================
    # User B cannot delete User A's job
    # =========================================================

    delete_a_by_b = client.delete(
        f"/api/jobs/{job_a_id}",
        headers=headers_b,
    )

    assert delete_a_by_b.status_code == 403

    # =========================================================
    # User A's job still exists
    # =========================================================

    verify_after_attack = client.get(
        f"/api/jobs/{job_a_id}",
        headers=headers_a,
    )

    assert verify_after_attack.status_code == 200

    # =========================================================
    # User A can delete their own job
    # =========================================================

    delete_a_by_a = client.delete(
        f"/api/jobs/{job_a_id}",
        headers=headers_a,
    )

    assert delete_a_by_a.status_code == 200

    # =========================================================
    # Deleted job is no longer accessible
    # =========================================================

    get_deleted_job = client.get(
        f"/api/jobs/{job_a_id}",
        headers=headers_a,
    )

    assert get_deleted_job.status_code == 404