"""Unit and integration tests for MediaStorageService and the /api/media streaming endpoint."""

from pathlib import Path
import io
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.media_storage_service import (
    DEFAULT_MEDIA_ROOT,
    MediaStorageError,
    MediaStorageService,
)

client = TestClient(app)


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

def test_get_media_from_outputs_job_directory():
    outputs_dir = Path("outputs") / "jobs" / "test_job_media" / "captioned"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    sample_file = outputs_dir / "short_1.mp4"
    sample_file.write_bytes(b"captioned vertical short bytes")

    # Serve via file_path (absolute)
    res1 = client.get(f"/api/media?file_path={sample_file.resolve()}")
    assert res1.status_code == 200
    assert res1.content == b"captioned vertical short bytes"
    assert "video/mp4" in res1.headers.get("content-type", "")

    # Serve via path (relative)
    res2 = client.get("/api/media?path=jobs/test_job_media/captioned/short_1.mp4")
    assert res2.status_code == 200
    assert res2.content == b"captioned vertical short bytes"


def test_get_media_subtitles_text_content_type():
    outputs_dir = Path("outputs") / "jobs" / "test_job_media" / "captioned"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    srt_file = outputs_dir / "subtitles.srt"
    srt_file.write_bytes(b"1\n00:00:00,000 --> 00:00:02,000\nHello world\n")

    res = client.get(f"/api/media?file_path={srt_file.resolve()}")
    assert res.status_code == 200
    assert "text/plain" in res.headers.get("content-type", "")


def test_get_media_missing_param_returns_400():
    res = client.get("/api/media")
    assert res.status_code == 400


def test_get_media_traversal_outside_approved_rejected():
    outside_file = Path("backend") / "app" / "main.py"
    res = client.get(f"/api/media?file_path={outside_file.resolve()}")
    assert res.status_code == 403


def test_get_media_relative_traversal_rejected():
    res = client.get("/api/media?path=../../backend/app/main.py")
    assert res.status_code in (403, 404)
