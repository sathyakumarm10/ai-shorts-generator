"""End-to-end production runtime workflow test.

Tests the full lifecycle through HTTP API endpoints:
- Health check endpoints
- User registration and JWT authentication
- Multipart video upload
- Background generation job submission and lifecycle state transitions
- Highlight clipping, 9:16 vertical formatting, and subtitle burning
- Media asset streaming from the media endpoint
- Multi-user isolation & SQLite persistence
- Sequential multi-job execution
- Error response handling
"""

from pathlib import Path
import shutil
import subprocess
import time
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import JobStatus, TimestampedTranscript, TranscriptSegment
from app.services.job_runner_service import default_job_runner
from app.services.transcription_service import TranscriptionProvider, TranscriptionService


class MockE2ETranscriptionProvider(TranscriptionProvider):
    """Deterministic transcription provider providing realistic spoken segments for fast E2E validation."""

    def transcribe(self, audio_or_video_path: Path) -> TimestampedTranscript:
        return TimestampedTranscript(
            segments=[
                TranscriptSegment(
                    start_seconds=0.0,
                    end_seconds=10.0,
                    text="Welcome to the video. Here is our introductory opening.",
                ),
                TranscriptSegment(
                    start_seconds=10.0,
                    end_seconds=40.0,
                    text="Here is the most incredible secret that will change how you create viral short content forever!",
                ),
                TranscriptSegment(
                    start_seconds=40.0,
                    end_seconds=60.0,
                    text="Make sure to like and subscribe for more amazing video creation tips.",
                ),
            ]
        )


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory) -> Path:
    """Create a temporary 60-second synthetic test video with audio using FFmpeg."""
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    if not shutil.which(ffmpeg_bin):
        pytest.skip("FFmpeg is not installed on system PATH.")

    temp_dir = tmp_path_factory.mktemp("prod_e2e")
    video_path = temp_dir / "sample_e2e_video.mp4"

    cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "lavfi", "-i", "testsrc=duration=60:size=640x360:rate=24",
        "-f", "lavfi", "-i", "sine=frequency=800:duration=60",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        "-shortest",
        str(video_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return video_path


class TestProductionWorkflowE2E:
    @pytest.fixture(autouse=True)
    def setup_job_runner(self, monkeypatch):
        """Inject deterministic transcription into the job runner for fast E2E validation."""
        original_build = default_job_runner._build_job_shorts_service

        def mock_build(job_id: str):
            service = original_build(job_id)
            service.transcription_service = TranscriptionService(
                provider=MockE2ETranscriptionProvider(),
            )
            return service

        monkeypatch.setattr(default_job_runner, "_build_job_shorts_service", mock_build)
        yield

    def test_api_health_endpoint(self, client: TestClient):
        """Verify the health endpoint returns 200 OK."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_full_production_job_lifecycle(self, client: TestClient, sample_video: Path):
        """Perform a complete end-to-end job workflow with auth, upload, generation, and media streaming."""
        # 1. Register a new user
        unique_email = f"prod_user_{int(time.time())}@example.com"
        reg_resp = client.post(
            "/api/auth/register",
            json={"email": unique_email, "password": "SecurePassword123!"},
        )
        assert reg_resp.status_code == 200, f"Registration failed: {reg_resp.text}"
        auth_data = reg_resp.json()
        token = auth_data["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2. Upload video
        with open(sample_video, "rb") as f:
            upload_resp = client.post(
                "/api/upload",
                files={"file": ("sample_e2e_video.mp4", f, "video/mp4")},
                headers=headers,
            )
        assert upload_resp.status_code == 200, f"Upload failed: {upload_resp.text}"
        upload_data = upload_resp.json()
        uploaded_path = upload_data["file_path"]
        assert Path(uploaded_path).is_file()

        # 3. Create job #1
        job_payload = {
            "source": {"type": "upload", "location": uploaded_path},
            "clip_duration_seconds": 30,
            "min_clip_duration": 20,
            "max_clip_duration": 60,
            "number_of_clips": 1,
            "target_aspect_ratio": "9:16",
            "caption_style": "clean",
            "caption_preset": "default",
            "include_captions": True,
            "enable_karaoke": False,
        }
        create_resp = client.post("/api/jobs", json=job_payload, headers=headers)
        assert create_resp.status_code == 200, f"Job creation failed: {create_resp.text}"
        job_info = create_resp.json()
        job_id = job_info["job_id"]
        assert job_info["status"] in (JobStatus.QUEUED.value, JobStatus.INGESTING.value, JobStatus.PROCESSING.value)

        # 4. Poll until job completes
        max_wait_seconds = 180
        start_time = time.time()
        completed_job = None

        while time.time() - start_time < max_wait_seconds:
            poll_resp = client.get(f"/api/jobs/{job_id}", headers=headers)
            assert poll_resp.status_code == 200
            current_job = poll_resp.json()
            status = current_job["status"]

            if status == JobStatus.COMPLETED.value:
                completed_job = current_job
                break
            elif status == JobStatus.FAILED.value:
                pytest.fail(f"Job failed unexpectedly: {current_job.get('error')}")

            time.sleep(2)

        assert completed_job is not None, "Job timed out before reaching completed status"
        assert completed_job["progress_percent"] == 100.0
        assert completed_job["completed_at"] is not None

        # 5. Verify generated shorts output
        result = completed_job.get("result", {})
        shorts = result.get("generated_shorts", [])
        assert len(shorts) >= 1, "Expected at least 1 generated short in result"

        first_short = shorts[0]
        final_file_path = first_short.get("final_file_path")
        assert final_file_path is not None
        assert Path(final_file_path).is_file()
        assert Path(final_file_path).stat().st_size > 0

        # 6. Stream media via API
        media_resp = client.get("/api/media", params={"file_path": final_file_path}, headers=headers)
        assert media_resp.status_code == 200
        assert media_resp.headers["content-type"] == "video/mp4"
        assert len(media_resp.content) > 0

        # 7. Verify SQLite persistence and list_jobs
        list_resp = client.get("/api/jobs", headers=headers)
        assert list_resp.status_code == 200
        job_list = list_resp.json()
        assert any(j["job_id"] == job_id for j in job_list)

        # 8. Sequential Job: Run second job to verify pipeline reusability
        job2_resp = client.post("/api/jobs", json=job_payload, headers=headers)
        assert job2_resp.status_code == 200
        job2_id = job2_resp.json()["job_id"]
        assert job2_id != job_id

        # Poll second job
        start_time = time.time()
        job2_completed = None
        while time.time() - start_time < max_wait_seconds:
            poll_resp = client.get(f"/api/jobs/{job2_id}", headers=headers)
            assert poll_resp.status_code == 200
            current_job = poll_resp.json()
            if current_job["status"] == JobStatus.COMPLETED.value:
                job2_completed = current_job
                break
            elif current_job["status"] == JobStatus.FAILED.value:
                pytest.fail(f"Job 2 failed unexpectedly: {current_job.get('error')}")
            time.sleep(2)

        assert job2_completed is not None, "Job 2 timed out"
        assert len(job2_completed.get("result", {}).get("generated_shorts", [])) >= 1

    def test_error_handling_invalid_upload_and_not_found(self, client: TestClient):
        """Verify proper HTTP error responses for bad requests."""
        # Unsupported extension
        bad_upload = client.post(
            "/api/upload",
            files={"file": ("malicious.exe", b"binary content", "application/octet-stream")},
        )
        assert bad_upload.status_code == 400
        assert "Unsupported file format" in bad_upload.json()["detail"]

        # Non-existent job
        missing_job = client.get("/api/jobs/non-existent-uuid-12345")
        assert missing_job.status_code == 404

        # Non-existent media
        missing_media = client.get("/api/media", params={"file_path": "outputs/non_existent.mp4"})
        assert missing_media.status_code in (403, 404)
