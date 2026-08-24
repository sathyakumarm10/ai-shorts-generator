"""Integration tests for real FFmpeg and ffprobe video clip generation.

These tests execute against the installed FFmpeg and ffprobe binaries on the
machine, creating a short synthetic video in a pytest temporary directory,
cutting a clip with `VideoClipService`, and verifying the output using
`VideoMetadataService` and `ffprobe`.

If FFmpeg or ffprobe is not installed on the system, the tests in this module
are automatically skipped with a clear reason.
"""

import shutil
import subprocess

import pytest

from app.models import IngestedVideo, VideoClipRequest
from app.services.media_tools_service import MediaToolsService
from app.services.video_clip_service import VideoClipService
from app.services.video_metadata_service import VideoMetadataService

# Check if both ffmpeg and ffprobe are available on the host
tools_report = MediaToolsService().check_all()
ffmpeg_available = tools_report.ffmpeg.available
ffprobe_available = tools_report.ffprobe.available

pytestmark = pytest.mark.skipif(
    not (ffmpeg_available and ffprobe_available),
    reason="FFmpeg and ffprobe must both be available on system PATH for real integration testing.",
)


def _create_synthetic_video(output_path, duration_seconds: int = 40):
    """Generate a lightweight synthetic test video using FFmpeg.

    Creates a 640x360 test pattern with synthesized test audio tone
    using FFmpeg's built-in `testsrc` and `sine` filters.
    """
    ffmpeg_cmd = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [
        ffmpeg_cmd,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size=640x360:rate=25",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1000:sample_rate=44100",
        "-t",
        str(duration_seconds),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to generate synthetic test video: {result.stderr}")


def test_real_ffmpeg_clip_generation(tmp_path):
    """Test cutting a real 30-second clip from a synthetic 40-second video with FFmpeg."""
    source_file = tmp_path / "synthetic_source.mp4"
    clips_dir = tmp_path / "clips"

    # 1. Create a 40-second synthetic source video
    _create_synthetic_video(source_file, duration_seconds=40)
    assert source_file.is_file()

    # 2. Extract metadata from the source video to verify input integrity
    metadata_service = VideoMetadataService()
    source_metadata = metadata_service.extract_metadata(source_file)
    assert source_metadata.duration_seconds >= 39.0

    # 3. Request a 30-second clip starting at 5 seconds
    clip_service = VideoClipService(output_dir=clips_dir)
    clip_request = VideoClipRequest(start_seconds=5.0, duration_seconds=30.0)

    generated_clip = clip_service.create_clip(
        video=IngestedVideo(file_path=str(source_file)),
        clip_request=clip_request,
        metadata=source_metadata,
    )

    # 4. Verify output file exists and is located in the temporary output directory
    clip_path = generated_clip.file_path
    assert (clips_dir / "clip_").name in clip_path or str(clips_dir) in clip_path
    assert (tmp_path / "clips").is_dir()

    # 5. Use ffprobe / VideoMetadataService to inspect the generated clip
    clip_metadata = metadata_service.extract_metadata(generated_clip)

    # Verify duration is approximately 30 seconds (tolerance within ±1 second for container boundaries)
    assert abs(clip_metadata.duration_seconds - 30.0) <= 1.0
    # Verify dimensions and container format
    assert clip_metadata.width == 640
    assert clip_metadata.height == 360
    assert "mp4" in clip_metadata.format.lower()
    assert clip_metadata.file_size_bytes > 0
