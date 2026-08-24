"""Tests for the video processing job API (`POST /api/jobs`).

These tests also confirm that the pre-existing `GET /` and `GET /health`
endpoints continue to work after adding the new job creation endpoint.
"""

from fastapi.testclient import TestClient

from app.main import app
from app.models import JobStatus

client = TestClient(app)

VALID_PAYLOAD = {
    "video_url": "https://www.youtube.com/watch?v=example",
    "clip_duration": 60,
    "number_of_clips": 5,
}


def _payload(**overrides):
    """Helper to build a request payload based on VALID_PAYLOAD with overrides."""
    payload = VALID_PAYLOAD.copy()
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------
# Existing endpoints should keep working.
# ---------------------------------------------------------------------


def test_read_root_still_works():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "AI Shorts Generator API is running"}


def test_health_check_still_works():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------
# POST /api/jobs - valid requests
# ---------------------------------------------------------------------


def test_create_job_with_valid_request_returns_expected_shape():
    response = client.post("/api/jobs", json=VALID_PAYLOAD)
    assert response.status_code == 200

    body = response.json()
    assert set(body.keys()) == {
        "job_id",
        "status",
        "video_url",
        "clip_duration",
        "number_of_clips",
        "created_at",
    }
    assert body["status"] == "queued"
    assert body["video_url"] == VALID_PAYLOAD["video_url"]
    assert body["clip_duration"] == VALID_PAYLOAD["clip_duration"]
    assert body["number_of_clips"] == VALID_PAYLOAD["number_of_clips"]
    # job_id should be a valid UUID4 string.
    import uuid

    uuid.UUID(body["job_id"], version=4)
    # created_at should be an ISO 8601 UTC timestamp that can be parsed.
    from datetime import datetime

    datetime.fromisoformat(body["created_at"])


def test_create_job_returns_unique_job_ids():
    response_1 = client.post("/api/jobs", json=VALID_PAYLOAD)
    response_2 = client.post("/api/jobs", json=VALID_PAYLOAD)
    assert response_1.json()["job_id"] != response_2.json()["job_id"]


def test_create_job_status_is_queued():
    response = client.post("/api/jobs", json=VALID_PAYLOAD)
    assert response.json()["status"] == "queued"


# ---------------------------------------------------------------------
# clip_duration boundary validation (30-120 inclusive)
# ---------------------------------------------------------------------


def test_clip_duration_minimum_boundary_accepted():
    response = client.post("/api/jobs", json=_payload(clip_duration=30))
    assert response.status_code == 200
    assert response.json()["clip_duration"] == 30


def test_clip_duration_maximum_boundary_accepted():
    response = client.post("/api/jobs", json=_payload(clip_duration=120))
    assert response.status_code == 200
    assert response.json()["clip_duration"] == 120


def test_clip_duration_below_minimum_rejected():
    response = client.post("/api/jobs", json=_payload(clip_duration=29))
    assert response.status_code == 422


def test_clip_duration_above_maximum_rejected():
    response = client.post("/api/jobs", json=_payload(clip_duration=121))
    assert response.status_code == 422


# ---------------------------------------------------------------------
# number_of_clips boundary validation (1-20 inclusive)
# ---------------------------------------------------------------------


def test_number_of_clips_minimum_boundary_accepted():
    response = client.post("/api/jobs", json=_payload(number_of_clips=1))
    assert response.status_code == 200
    assert response.json()["number_of_clips"] == 1


def test_number_of_clips_maximum_boundary_accepted():
    response = client.post("/api/jobs", json=_payload(number_of_clips=20))
    assert response.status_code == 200
    assert response.json()["number_of_clips"] == 20


def test_number_of_clips_below_minimum_rejected():
    response = client.post("/api/jobs", json=_payload(number_of_clips=0))
    assert response.status_code == 422


def test_number_of_clips_above_maximum_rejected():
    response = client.post("/api/jobs", json=_payload(number_of_clips=21))
    assert response.status_code == 422


# ---------------------------------------------------------------------
# Other validation cases
# ---------------------------------------------------------------------


def test_missing_required_field_rejected():
    incomplete_payload = {"clip_duration": 60, "number_of_clips": 5}
    response = client.post("/api/jobs", json=incomplete_payload)
    assert response.status_code == 422


def test_invalid_video_url_rejected():
    response = client.post("/api/jobs", json=_payload(video_url="not-a-valid-url"))
    assert response.status_code == 422


def test_empty_video_url_rejected():
    response = client.post("/api/jobs", json=_payload(video_url=""))
    assert response.status_code == 422


# ---------------------------------------------------------------------
# GET /api/jobs/{job_id} - retrieving an existing job
# ---------------------------------------------------------------------


def test_get_job_returns_created_job():
    create_response = client.post("/api/jobs", json=VALID_PAYLOAD)
    assert create_response.status_code == 200
    created_job = create_response.json()
    job_id = created_job["job_id"]

    get_response = client.get(f"/api/jobs/{job_id}")
    assert get_response.status_code == 200

    fetched_job = get_response.json()
    assert fetched_job["job_id"] == job_id
    assert fetched_job["status"] == "queued"
    assert fetched_job["clip_duration"] == VALID_PAYLOAD["clip_duration"]
    assert fetched_job["number_of_clips"] == VALID_PAYLOAD["number_of_clips"]
    assert fetched_job["video_url"] == VALID_PAYLOAD["video_url"]


# ---------------------------------------------------------------------
# GET /api/jobs/{job_id} - nonexistent job
# ---------------------------------------------------------------------


def test_get_nonexistent_job_returns_404():
    response = client.get("/api/jobs/nonexistent-id")
    assert response.status_code == 404
    assert response.json() == {"detail": "Job not found"}


# ---------------------------------------------------------------------
# JobStatus enum
# ---------------------------------------------------------------------


def test_job_status_enum_contains_exactly_the_four_allowed_statuses():
    assert {member.value for member in JobStatus} == {
        "queued",
        "processing",
        "completed",
        "failed",
    }


def test_job_status_enum_values_are_plain_strings():
    # JobStatus inherits from str, so members should compare equal to and
    # behave like ordinary strings (important for JSON serialization).
    assert JobStatus.QUEUED == "queued"
    assert isinstance(JobStatus.QUEUED, str)


# ---------------------------------------------------------------------
# Job service unit tests
# ---------------------------------------------------------------------


def test_job_service_create_and_get_job():
    import uuid
    from app.models import VideoJobRequest
    from app.services import job_service

    request = VideoJobRequest(
        video_url="https://www.youtube.com/watch?v=example",
        clip_duration=60,
        number_of_clips=5,
    )
    created = job_service.create_job(request)

    assert created.status == JobStatus.QUEUED
    assert uuid.UUID(created.job_id, version=4)
    assert created.job_id in job_service.jobs
    assert job_service.get_job(created.job_id) == created


def test_job_service_get_job_nonexistent_returns_none():
    from app.services import job_service

    assert job_service.get_job("nonexistent-service-id") is None

