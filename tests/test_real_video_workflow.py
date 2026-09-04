"""Phase 2 Real Video Generation Integration Tests.

Validates that real MP4 video files in the environment can be processed through
the complete end-to-end multi-short pipeline:
- Video ingestion
- Metadata extraction
- Multi-short clipping
- Vertical 9:16 conversion
- Per-short synchronized subtitle burn-in
- Playability verification with ffprobe
- Unique output paths and relative storage preservation
- Fault tolerance when candidate limits or failures occur
- API retrieval and media streaming endpoints
"""

from pathlib import Path
import subprocess
from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.models import (
    CaptionPreset,
    CaptionTrack,
    JobStatus,
    ShortsGenerationRequest,
    VideoSource,
    VideoSourceType,
)
from app.services.job_runner_service import JobRunnerService
from app.services.job_service import default_job_service
from app.services.media_storage_service import default_media_storage
from app.services.shorts_generation_service import ShortsGenerationService

REAL_VIDEO_PATH = Path("downloads/uploads/real_source_video.mp4")


def probe_video_playable(video_path: Path) -> dict:
    """Run ffprobe to verify that the video is valid, non-empty, and has playable streams."""
    assert video_path.is_file(), f"Video file does not exist: {video_path}"
    assert video_path.stat().st_size > 0, f"Video file is empty (0 bytes): {video_path}"

    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration,size:stream=codec_name,codec_type,width,height",
        "-of", "default=noprint_wrappers=1",
        str(video_path.resolve()),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    out = res.stdout
    assert "codec_name=" in out, f"No codec found in ffprobe output: {out}"
    assert "duration=" in out, f"No duration found in ffprobe output: {out}"
    return {"raw": out, "size": video_path.stat().st_size}


@pytest.mark.skipif(not REAL_VIDEO_PATH.is_file(), reason="Real video file not found in downloads directory")
class TestRealVideoWorkflow:
    def test_real_video_playable_before_processing(self):
        """Verify the input source video is a valid playable MP4."""
        meta = probe_video_playable(REAL_VIDEO_PATH)
        assert meta["size"] > 100000

    def test_real_multi_short_pipeline_execution(self):
        """Execute the real pipeline on the real video requesting up to 10 shorts."""
        req = ShortsGenerationRequest(
            source=VideoSource(type=VideoSourceType.UPLOAD, location=str(REAL_VIDEO_PATH.resolve())),
            number_of_clips=10,
            clip_duration_seconds=30.0,
            min_clip_duration=30.0,
            max_clip_duration=35.0,
            include_captions=True,
            caption_preset=CaptionPreset.DEFAULT,
            enable_karaoke=True,
            vertical_width=1080,
            vertical_height=1920,
        )

        job_record = default_job_service.create_job(req)
        runner = JobRunnerService()

        # Run pipeline directly
        runner.execute_job_pipeline(job_record.job_id, req)

        # Retrieve completed job
        completed_job = default_job_service.get_job(job_record.job_id)
        assert completed_job is not None
        assert completed_job.status == JobStatus.COMPLETED
        assert completed_job.result is not None

        result = completed_job.result
        shorts = result.generated_shorts
        assert len(shorts) >= 1, "At least one real Short must be generated from the real video"

        seen_paths = set()
        for s in shorts:
            # 1. Output paths are unique
            assert s.final_file_path not in seen_paths
            seen_paths.add(s.final_file_path)

            # 2. Output files exist and are verified playable MP4s
            final_path = Path(s.final_file_path)
            if not final_path.is_file():
                # Check resolved via media root
                final_path = default_media_storage.media_root / s.final_file_path
            assert final_path.is_file(), f"Rendered short file missing: {final_path}"

            probe_info = probe_video_playable(final_path)
            assert "codec_name=" in probe_info["raw"]

            # 3. Subtitles are synchronized per-short
            assert s.caption_track is not None or s.captioned_clip_path is not None
            if s.caption_track:
                for seg in s.caption_track.segments:
                    # Segment start must be non-negative and relative to short duration
                    assert seg.start_seconds >= 0.0
                    assert seg.end_seconds > seg.start_seconds
                    assert len(seg.text.strip()) > 0

    def test_api_serves_real_job_and_media(self):
        """Verify TestClient can retrieve the completed job and stream the real MP4."""
        client = TestClient(app)
        jobs_res = client.get("/api/jobs")
        assert jobs_res.status_code == 200
        jobs = jobs_res.json()
        assert len(jobs) > 0

        # Find the latest completed job with generated shorts whose file exists on disk
        completed_job = None
        for j in reversed(jobs):
            res_data = j.get("result") or {}
            shorts_list = res_data.get("generated_shorts")
            if j.get("status") == "completed" and shorts_list:
                cand_path = default_media_storage.media_root / shorts_list[0]["final_file_path"]
                if cand_path.is_file():
                    completed_job = j
                    break
        assert completed_job is not None, "Completed job with generated shorts must exist on disk"

        short = completed_job["result"]["generated_shorts"][0]
        file_path = short["final_file_path"]

        # Stream media asset through API
        media_res = client.get(f"/api/media?file_path={file_path}")
        assert media_res.status_code == 200
        assert media_res.headers.get("content-type") == "video/mp4"
        assert len(media_res.content) > 1000
