"""Tests for the video processing job API (`POST /api/jobs`).

These tests also confirm that the pre-existing `GET /` and `GET /health`
endpoints continue to work after adding the new job creation endpoint.
"""

from concurrent.futures import Future
from unittest.mock import MagicMock
# pyrefly: ignore [missing-import]
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import IngestedVideo, JobStatus, VideoJobRequest, VideoSource, VideoSourceType
from app.services import job_service
from app.services.job_runner_service import default_job_runner

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_background_runner(monkeypatch):
    """Prevent background execution threads from attempting real downloads during API unit tests."""
    mock_submit = MagicMock(return_value=Future())
    monkeypatch.setattr(default_job_runner, "submit_job", mock_submit)
    return mock_submit


VALID_PAYLOAD = {
    "source": {
        "type": "youtube",
        "location": "https://www.youtube.com/watch?v=example",
    },
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
    assert response.json()["status"] == "ok"


# ---------------------------------------------------------------------
# POST /api/jobs - valid requests
# ---------------------------------------------------------------------


def test_create_job_with_valid_youtube_request_returns_expected_shape():
    response = client.post("/api/jobs", json=VALID_PAYLOAD)
    assert response.status_code == 200

    body = response.json()
    assert {"job_id", "status", "source", "clip_duration", "number_of_clips", "created_at"}.issubset(set(body.keys()))
    assert body["status"] == "queued"
    assert body["source"] == {
        "type": "youtube",
        "location": "https://www.youtube.com/watch?v=example",
    }
    assert body["clip_duration"] == VALID_PAYLOAD["clip_duration"]
    assert body["number_of_clips"] == VALID_PAYLOAD["number_of_clips"]
    # job_id should be a valid UUID4 string.
    import uuid

    uuid.UUID(body["job_id"], version=4)
    # created_at should be an ISO 8601 UTC timestamp that can be parsed.
    from datetime import datetime

    datetime.fromisoformat(body["created_at"])


def test_create_job_with_valid_upload_request():
    upload_payload = {
        "source": {
            "type": "upload",
            "location": "/uploads/user_video.mp4",
        },
        "clip_duration": 45,
        "number_of_clips": 3,
    }
    response = client.post("/api/jobs", json=upload_payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["source"] == {
        "type": "upload",
        "location": "/uploads/user_video.mp4",
    }
    assert body["clip_duration"] == 45
    assert body["number_of_clips"] == 3


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
# Other validation cases for POST /api/jobs
# ---------------------------------------------------------------------


def test_missing_source_rejected():
    payload = {"clip_duration": 60, "number_of_clips": 5}
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 422


def test_missing_clip_duration_rejected():
    payload = {
        "source": {
            "type": "youtube",
            "location": "https://www.youtube.com/watch?v=example",
        },
        "number_of_clips": 5,
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 422


def test_missing_number_of_clips_rejected():
    payload = {
        "source": {
            "type": "youtube",
            "location": "https://www.youtube.com/watch?v=example",
        },
        "clip_duration": 60,
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 422


def test_invalid_source_type_rejected():
    payload = _payload(source={"type": "vimeo", "location": "https://vimeo.com/123"})
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 422


def test_invalid_youtube_url_rejected():
    payload = _payload(source={"type": "youtube", "location": "not-a-valid-url"})
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 422


def test_empty_upload_location_rejected():
    payload = _payload(source={"type": "upload", "location": ""})
    response = client.post("/api/jobs", json=payload)
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
    assert fetched_job["source"] == VALID_PAYLOAD["source"]


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


def test_job_status_enum_contains_pipeline_statuses():
    expected = {
        "queued",
        "ingesting",
        "extracting_metadata",
        "transcribing",
        "finding_highlights",
        "generating_clips",
        "converting_vertical",
        "adding_captions",
        "completed",
        "failed",
        "processing",
    }
    assert {member.value for member in JobStatus} == expected


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

    request = VideoJobRequest(
        source=VideoSource(
            type=VideoSourceType.YOUTUBE,
            location="https://www.youtube.com/watch?v=example",
        ),
        clip_duration=60,
        number_of_clips=5,
    )
    created = job_service.create_job(request)

    assert created.status == JobStatus.QUEUED
    assert uuid.UUID(created.job_id, version=4)
    assert created.source is not None
    assert created.source.type == VideoSourceType.YOUTUBE
    assert created.source.location == "https://www.youtube.com/watch?v=example"
    assert created.job_id in job_service.jobs
    assert job_service.get_job(created.job_id) == created


def test_job_service_get_job_nonexistent_returns_none():
    assert job_service.get_job("nonexistent-service-id") is None


# ---------------------------------------------------------------------
# VideoSource & VideoSourceType unit tests
# ---------------------------------------------------------------------


def test_video_source_type_enum_members():
    assert {member.value for member in VideoSourceType} == {"youtube", "upload"}
    assert VideoSourceType.YOUTUBE == "youtube"
    assert VideoSourceType.UPLOAD == "upload"
    assert isinstance(VideoSourceType.YOUTUBE, str)


def test_valid_youtube_video_source():
    source = VideoSource(
        type=VideoSourceType.YOUTUBE,
        location="https://www.youtube.com/watch?v=12345",
    )
    assert source.type == VideoSourceType.YOUTUBE
    assert source.location == "https://www.youtube.com/watch?v=12345"


def test_valid_upload_video_source():
    source = VideoSource(
        type=VideoSourceType.UPLOAD,
        location="/path/to/local/video.mp4",
    )
    assert source.type == VideoSourceType.UPLOAD
    assert source.location == "/path/to/local/video.mp4"


def test_video_source_missing_type_rejected():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        VideoSource.model_validate({"location": "https://www.youtube.com/watch?v=test"})


def test_video_source_missing_location_rejected():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        VideoSource.model_validate({"type": VideoSourceType.YOUTUBE})


def test_video_source_unsupported_type_rejected():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        VideoSource.model_validate({"type": "vimeo", "location": "https://vimeo.com/123"})


def test_video_source_invalid_youtube_url_rejected():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        VideoSource(type=VideoSourceType.YOUTUBE, location="not-a-valid-url")


def test_video_source_empty_upload_location_rejected():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        VideoSource(type=VideoSourceType.UPLOAD, location="")


# ---------------------------------------------------------------------
# IngestedVideo & VideoIngestionService unit tests
# ---------------------------------------------------------------------


def test_valid_ingested_video_model():
    from app.models import IngestedVideo

    ingested = IngestedVideo(file_path="/tmp/videos/test_video.mp4")
    assert ingested.file_path == "/tmp/videos/test_video.mp4"


def test_ingested_video_empty_path_rejected():
    import pytest
    from pydantic import ValidationError
    from app.models import IngestedVideo

    with pytest.raises(ValidationError):
        IngestedVideo(file_path="")


def test_youtube_ingestion_successful(monkeypatch, tmp_path):
    from pathlib import Path
    from app.services.video_ingestion_service import VideoIngestionService

    service = VideoIngestionService(download_dir=tmp_path)
    youtube_source = VideoSource(
        type=VideoSourceType.YOUTUBE,
        location="https://www.youtube.com/watch?v=example",
    )

    fake_video_file = tmp_path / "yt_test123.mp4"

    class FakeYoutubeDL:
        def __init__(self, params=None):
            self.params = params or {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def extract_info(self, url, download=True):
            assert url == "https://www.youtube.com/watch?v=example"
            # Simulate downloaded file created on disk
            fake_video_file.write_text("fake video content")
            return {"id": "example", "ext": "mp4"}

        def prepare_filename(self, info_dict):
            return str(fake_video_file)

    monkeypatch.setattr("yt_dlp.YoutubeDL", FakeYoutubeDL)

    ingested = service.ingest(youtube_source)
    assert ingested.file_path == str(fake_video_file)
    assert Path(ingested.file_path).is_file()


def test_youtube_ingestion_failure_raises_video_ingestion_error(monkeypatch, tmp_path):
    import pytest
    from app.services.video_ingestion_service import VideoIngestionError, VideoIngestionService

    service = VideoIngestionService(download_dir=tmp_path)
    youtube_source = VideoSource(
        type=VideoSourceType.YOUTUBE,
        location="https://www.youtube.com/watch?v=example",
    )

    class FailingYoutubeDL:
        def __init__(self, params=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def extract_info(self, url, download=True):
            raise RuntimeError("Network timeout connecting to video host")

    monkeypatch.setattr("yt_dlp.YoutubeDL", FailingYoutubeDL)

    with pytest.raises(VideoIngestionError, match="Failed to download YouTube video"):
        service.ingest(youtube_source)


def test_youtube_ingestion_missing_output_file_raises_error(monkeypatch, tmp_path):
    import pytest
    from app.services.video_ingestion_service import VideoIngestionError, VideoIngestionService

    service = VideoIngestionService(download_dir=tmp_path)
    youtube_source = VideoSource(
        type=VideoSourceType.YOUTUBE,
        location="https://www.youtube.com/watch?v=example",
    )

    class MissingFileYoutubeDL:
        def __init__(self, params=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def extract_info(self, url, download=True):
            # Extract info returns success but does not create the file
            return {"id": "example", "ext": "mp4"}

        def prepare_filename(self, info_dict):
            return str(tmp_path / "nonexistent.mp4")

    monkeypatch.setattr("yt_dlp.YoutubeDL", MissingFileYoutubeDL)

    with pytest.raises(VideoIngestionError, match="expected video file was not found"):
        service.ingest(youtube_source)


def test_upload_ingestion_remains_not_implemented(tmp_path):
    import pytest
    from app.services.video_ingestion_service import VideoIngestionService

    service = VideoIngestionService(download_dir=tmp_path)
    upload_source = VideoSource(
        type=VideoSourceType.UPLOAD,
        location="/local/path/video.mp4",
    )

    with pytest.raises(NotImplementedError, match="Upload video ingestion is not implemented yet"):
        service.ingest(upload_source)


# ---------------------------------------------------------------------
# VideoMetadata & VideoMetadataService unit tests
# ---------------------------------------------------------------------


def test_video_metadata_model_validation():
    import pytest
    from pydantic import ValidationError
    from app.models import VideoMetadata

    meta = VideoMetadata(
        duration_seconds=124.5,
        width=1920,
        height=1080,
        format="mov,mp4,m4a,3gp,3g2,mj2",
        file_size_bytes=1048576,
    )
    assert meta.duration_seconds == 124.5
    assert meta.width == 1920
    assert meta.height == 1080
    assert meta.format == "mov,mp4,m4a,3gp,3g2,mj2"
    assert meta.file_size_bytes == 1048576

    # Zero or negative duration rejected
    with pytest.raises(ValidationError):
        VideoMetadata(
            duration_seconds=0.0,
            width=1920,
            height=1080,
            format="mp4",
            file_size_bytes=100,
        )


def test_video_metadata_service_missing_input_file(tmp_path):
    import pytest
    from app.models import IngestedVideo
    from app.services.video_metadata_service import VideoMetadataError, VideoMetadataService

    service = VideoMetadataService()
    nonexistent = IngestedVideo(file_path=str(tmp_path / "nonexistent.mp4"))

    with pytest.raises(VideoMetadataError, match="Video file not found"):
        service.extract_metadata(nonexistent)


def test_video_metadata_service_successful_extraction(monkeypatch, tmp_path):
    import json
    from app.models import IngestedVideo
    from app.services.video_metadata_service import VideoMetadataService

    video_file = tmp_path / "sample.mp4"
    video_file.write_bytes(b"0" * 2048)  # 2048 bytes file size

    mock_ffprobe_output = {
        "format": {
            "duration": "120.45",
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        },
        "streams": [
            {
                "width": 1920,
                "height": 1080,
            }
        ],
    }

    class MockCompletedProcess:
        returncode = 0
        stdout = json.dumps(mock_ffprobe_output)
        stderr = ""

    def mock_run(cmd, capture_output, text, check):
        assert str(video_file) in cmd
        return MockCompletedProcess()

    monkeypatch.setattr("subprocess.run", mock_run)

    service = VideoMetadataService()
    metadata = service.extract_metadata(IngestedVideo(file_path=str(video_file)))

    assert metadata.duration_seconds == 120.45
    assert metadata.width == 1920
    assert metadata.height == 1080
    assert metadata.format == "mov,mp4,m4a,3gp,3g2,mj2"
    assert metadata.file_size_bytes == 2048


def test_video_metadata_service_ffprobe_failure(monkeypatch, tmp_path):
    import pytest
    from app.models import IngestedVideo
    from app.services.video_metadata_service import VideoMetadataError, VideoMetadataService

    video_file = tmp_path / "corrupt.mp4"
    video_file.write_bytes(b"corrupt")

    class FailingProcess:
        returncode = 1
        stdout = ""
        stderr = "Invalid data found when processing input"

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: FailingProcess())

    service = VideoMetadataService()
    with pytest.raises(VideoMetadataError, match="ffprobe inspection failed"):
        service.extract_metadata(IngestedVideo(file_path=str(video_file)))


def test_video_metadata_service_malformed_json_output(monkeypatch, tmp_path):
    import pytest
    from app.models import IngestedVideo
    from app.services.video_metadata_service import VideoMetadataError, VideoMetadataService

    video_file = tmp_path / "sample.mp4"
    video_file.write_bytes(b"data")

    class MalformedProcess:
        returncode = 0
        stdout = "not-json-content"
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: MalformedProcess())

    service = VideoMetadataService()
    with pytest.raises(VideoMetadataError, match="Failed to parse ffprobe JSON output"):
        service.extract_metadata(IngestedVideo(file_path=str(video_file)))


def test_video_metadata_service_missing_duration_or_streams(monkeypatch, tmp_path):
    import json
    import pytest
    from app.models import IngestedVideo
    from app.services.video_metadata_service import VideoMetadataError, VideoMetadataService

    video_file = tmp_path / "sample.mp4"
    video_file.write_bytes(b"data")

    # Missing duration
    class MissingDurationProcess:
        returncode = 0
        stdout = json.dumps({"format": {"format_name": "mp4"}, "streams": [{"width": 1920, "height": 1080}]})
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: MissingDurationProcess())
    service = VideoMetadataService()

    with pytest.raises(VideoMetadataError, match="ffprobe output does not contain duration information"):
        service.extract_metadata(IngestedVideo(file_path=str(video_file)))

    # Missing streams
    class MissingStreamsProcess:
        returncode = 0
        stdout = json.dumps({"format": {"duration": "60.0", "format_name": "mp4"}, "streams": []})
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: MissingStreamsProcess())

    with pytest.raises(VideoMetadataError, match="No video streams found in the media file"):
        service.extract_metadata(IngestedVideo(file_path=str(video_file)))


# ---------------------------------------------------------------------
# MediaToolsService unit tests
# ---------------------------------------------------------------------


def test_media_tools_all_available(monkeypatch):
    from app.services.media_tools_service import MediaToolsService

    def mock_which(cmd, path=None):
        return f"/usr/bin/{cmd}"

    monkeypatch.setattr("shutil.which", mock_which)

    service = MediaToolsService()
    report = service.check_all()

    assert report.ffmpeg.available is True
    assert report.ffmpeg.path is not None
    assert "ffmpeg" in report.ffmpeg.path

    assert report.ffprobe.available is True
    assert report.ffprobe.path is not None
    assert "ffprobe" in report.ffprobe.path

    assert report.yt_dlp.available is True
    assert report.yt_dlp.path is not None
    assert "yt-dlp" in report.yt_dlp.path


def test_media_tools_ffmpeg_unavailable(monkeypatch):
    from app.services.media_tools_service import MediaToolsService

    def mock_which(cmd, path=None):
        if cmd == "ffmpeg":
            return None
        return f"/usr/bin/{cmd}"

    monkeypatch.setattr("shutil.which", mock_which)

    service = MediaToolsService()
    report = service.check_all()

    assert report.ffmpeg.available is False
    assert report.ffmpeg.path is None
    assert report.ffprobe.available is True
    assert report.yt_dlp.available is True


def test_media_tools_ffprobe_unavailable(monkeypatch):
    from app.services.media_tools_service import MediaToolsService

    def mock_which(cmd, path=None):
        if cmd == "ffprobe":
            return None
        return f"/usr/bin/{cmd}"

    monkeypatch.setattr("shutil.which", mock_which)

    service = MediaToolsService()
    report = service.check_all()

    assert report.ffmpeg.available is True
    assert report.ffprobe.available is False
    assert report.ffprobe.path is None
    assert report.yt_dlp.available is True


def test_media_tools_yt_dlp_unavailable(monkeypatch):
    from app.services.media_tools_service import MediaToolsService

    def mock_which(cmd, path=None):
        if cmd == "yt-dlp":
            return None
        return f"/usr/bin/{cmd}"

    monkeypatch.setattr("shutil.which", mock_which)

    service = MediaToolsService()
    report = service.check_all()

    assert report.ffmpeg.available is True
    assert report.ffprobe.available is True
    assert report.yt_dlp.available is False
    assert report.yt_dlp.path is None


def test_media_tools_all_unavailable(monkeypatch):
    from app.services.media_tools_service import MediaToolsService

    monkeypatch.setattr("shutil.which", lambda cmd, path=None: None)

    service = MediaToolsService()
    report = service.check_all()

    assert report.ffmpeg.available is False
    assert report.ffmpeg.path is None
    assert report.ffprobe.available is False
    assert report.ffprobe.path is None
    assert report.yt_dlp.available is False
    assert report.yt_dlp.path is None


# ---------------------------------------------------------------------
# VideoClipRequest & VideoClipService unit tests
# ---------------------------------------------------------------------


def test_video_clip_request_validation():
    import pytest
    from pydantic import ValidationError
    from app.models import VideoClipRequest

    # Valid boundary cases (30, 60, 120)
    req30 = VideoClipRequest(start_seconds=0.0, duration_seconds=30.0)
    assert req30.start_seconds == 0.0
    assert req30.duration_seconds == 30.0

    req60 = VideoClipRequest(start_seconds=15.5, duration_seconds=60.0)
    assert req60.start_seconds == 15.5
    assert req60.duration_seconds == 60.0

    req120 = VideoClipRequest(start_seconds=100.0, duration_seconds=120.0)
    assert req120.duration_seconds == 120.0

    # Duration below 30 rejected
    with pytest.raises(ValidationError):
        VideoClipRequest(start_seconds=0.0, duration_seconds=29.9)

    # Duration above 120 rejected
    with pytest.raises(ValidationError):
        VideoClipRequest(start_seconds=0.0, duration_seconds=120.1)

    # Negative start time rejected
    with pytest.raises(ValidationError):
        VideoClipRequest(start_seconds=-1.0, duration_seconds=30.0)

    # NaN or infinite values rejected
    with pytest.raises(ValidationError):
        VideoClipRequest(start_seconds=float("nan"), duration_seconds=30.0)

    with pytest.raises(ValidationError):
        VideoClipRequest(start_seconds=0.0, duration_seconds=float("inf"))


def test_video_clip_service_missing_input_file(tmp_path):
    import pytest
    from app.models import IngestedVideo, VideoClipRequest
    from app.services.video_clip_service import VideoClipError, VideoClipService

    service = VideoClipService(output_dir=tmp_path)
    nonexistent = IngestedVideo(file_path=str(tmp_path / "missing.mp4"))
    req = VideoClipRequest(start_seconds=0.0, duration_seconds=30.0)

    with pytest.raises(VideoClipError, match="Source video file not found"):
        service.create_clip(nonexistent, req)


def test_video_clip_service_start_beyond_metadata_duration(tmp_path):
    import pytest
    from app.models import IngestedVideo, VideoClipRequest, VideoMetadata
    from app.services.video_clip_service import VideoClipError, VideoClipService

    source_file = tmp_path / "source.mp4"
    source_file.write_bytes(b"dummy video")

    meta = VideoMetadata(
        duration_seconds=50.0,
        width=1920,
        height=1080,
        format="mp4",
        file_size_bytes=1024,
    )

    service = VideoClipService(output_dir=tmp_path)
    req = VideoClipRequest(start_seconds=55.0, duration_seconds=30.0)

    with pytest.raises(VideoClipError, match="is at or beyond source video duration"):
        service.create_clip(IngestedVideo(file_path=str(source_file)), req, metadata=meta)


def test_video_clip_service_successful_ffmpeg_execution(monkeypatch, tmp_path):
    from pathlib import Path
    from app.models import IngestedVideo, VideoClipRequest
    from app.services.video_clip_service import VideoClipService

    source_file = tmp_path / "source.mp4"
    source_file.write_bytes(b"source data")

    output_dir = tmp_path / "clips"

    recorded_cmd = []

    class MockCompletedProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    def mock_subprocess_run(cmd, capture_output, text, check):
        # Verify shell=False / list of args
        assert isinstance(cmd, list)
        recorded_cmd.extend(cmd)
        # Output file is the last argument
        out_file = Path(cmd[-1])
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(b"generated clip content")
        return MockCompletedProcess()

    monkeypatch.setattr("subprocess.run", mock_subprocess_run)

    service = VideoClipService(output_dir=output_dir)
    req = VideoClipRequest(start_seconds=10.0, duration_seconds=45.0)

    clip = service.create_clip(IngestedVideo(file_path=str(source_file)), req)

    assert Path(clip.file_path).is_file()
    assert str(output_dir) in clip.file_path
    # Verify FFmpeg parameters in recorded command
    assert "-ss" in recorded_cmd
    assert "10.0" in recorded_cmd
    assert "-i" in recorded_cmd
    assert str(source_file) in recorded_cmd
    assert "-t" in recorded_cmd
    assert "45.0" in recorded_cmd


def test_video_clip_service_ffmpeg_failure(monkeypatch, tmp_path):
    import pytest
    from app.models import IngestedVideo, VideoClipRequest
    from app.services.video_clip_service import VideoClipError, VideoClipService

    source_file = tmp_path / "source.mp4"
    source_file.write_bytes(b"source data")

    class FailingProcess:
        returncode = 1
        stdout = ""
        stderr = "Error while decoding stream #0:0"

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: FailingProcess())

    service = VideoClipService(output_dir=tmp_path)
    req = VideoClipRequest(start_seconds=0.0, duration_seconds=30.0)

    with pytest.raises(VideoClipError, match="FFmpeg clip generation failed"):
        service.create_clip(IngestedVideo(file_path=str(source_file)), req)


def test_video_clip_service_missing_output_file(monkeypatch, tmp_path):
    import pytest
    from app.models import IngestedVideo, VideoClipRequest
    from app.services.video_clip_service import VideoClipError, VideoClipService

    source_file = tmp_path / "source.mp4"
    source_file.write_bytes(b"source data")

    class SuccessProcessNoFile:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: SuccessProcessNoFile())

    service = VideoClipService(output_dir=tmp_path)
    req = VideoClipRequest(start_seconds=0.0, duration_seconds=30.0)

    with pytest.raises(VideoClipError, match="generated clip was not found"):
        service.create_clip(IngestedVideo(file_path=str(source_file)), req)


# ---------------------------------------------------------------------
# ShortsGenerationRequest POST /api/jobs & JobRecord GET /api/jobs/{id}
# ---------------------------------------------------------------------


def test_create_job_with_shorts_generation_request_payload():
    payload = {
        "source": {
            "type": "upload",
            "location": "/uploads/my_podcast.mp4",
        },
        "clip_duration_seconds": 45.0,
        "number_of_clips": 3,
        "include_captions": True,
        "vertical_width": 1080,
        "vertical_height": 1920,
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["progress_percent"] == 0.0
    assert "job_id" in body
    assert body["message"] == "Job queued"


def test_get_completed_job_record_exposes_results_and_metadata():
    from app.models import (
        GeneratedShort,
        HighlightCandidate,
        HighlightScore,
        ShortsGenerationRequest,
        ShortsGenerationResult,
        TimestampedTranscript,
        VideoMetadata,
    )
    from app.services.job_service import default_job_service

    req = ShortsGenerationRequest(
        source=VideoSource(type=VideoSourceType.UPLOAD, location="video.mp4"),
        clip_duration_seconds=30.0,
        number_of_clips=1,
    )
    job = default_job_service.create_job(req)
    cand = HighlightCandidate(
        start_seconds=5.0,
        end_seconds=35.0,
        duration_seconds=30.0,
        text="Hook transcript text",
        score=HighlightScore(overall=0.95, hook=0.9, emotion=0.9, curiosity=0.9, information_density=0.9),
    )
    short = GeneratedShort(
        index=1,
        candidate=cand,
        source_clip_path="clip.mp4",
        vertical_clip_path="v.mp4",
        captioned_clip_path="cap.mp4",
        final_file_path="cap.mp4",
    )
    result = ShortsGenerationResult(
        source_video=IngestedVideo(file_path="video.mp4"),
        metadata=VideoMetadata(duration_seconds=60.0, width=1920, height=1080, format="mp4", file_size_bytes=2048),
        transcript=TimestampedTranscript(segments=[]),
        candidates=[cand],
        generated_shorts=[short],
    )
    default_job_service.complete_job(job.job_id, result)

    response = client.get(f"/api/jobs/{job.job_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["progress_percent"] == 100.0
    assert body["result"] is not None
    assert len(body["result"]["generated_shorts"]) == 1
    assert body["result"]["generated_shorts"][0]["final_file_path"] == "cap.mp4"
    assert body["result"]["generated_shorts"][0]["candidate"]["score"]["overall"] == 0.95


def test_get_failed_job_record_exposes_error():
    from app.models import ShortsGenerationRequest
    from app.services.job_service import default_job_service

    req = ShortsGenerationRequest(
        source=VideoSource(type=VideoSourceType.UPLOAD, location="invalid.mp4"),
        clip_duration_seconds=30.0,
        number_of_clips=1,
    )
    job = default_job_service.create_job(req)
    default_job_service.fail_job(job.job_id, "Corrupt audio stream in source video")

    response = client.get(f"/api/jobs/{job.job_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert "Corrupt audio stream" in body["error"]






