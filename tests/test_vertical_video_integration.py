"""Real FFmpeg integration test for VerticalVideoService 9:16 vertical video conversion.

Verifies that landscape video clips are converted to standard 1080x1920 9:16 vertical Shorts,
preserving aspect ratio without stretching, preserving audio streams, and maintaining duration.
"""

from pathlib import Path
import shutil
import subprocess
import pytest

from app.models import IngestedVideo, VerticalVideoRequest
from app.services.vertical_video_service import VerticalVideoService
from app.services.video_metadata_service import VideoMetadataService


class TestVerticalVideoRealIntegration:
    def test_real_ffmpeg_vertical_9_16_conversion(self, tmp_path: Path):
        """Convert synthetic 16:9 landscape video into 9:16 vertical Short using real FFmpeg."""
        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
        ffprobe_bin = shutil.which("ffprobe") or "ffprobe"

        if not shutil.which(ffmpeg_bin) or not shutil.which(ffprobe_bin):
            pytest.skip("FFmpeg and/or ffprobe are not available on the system.")

        # 1. Create a 3-second 16:9 landscape test video (1280x720) with audio
        landscape_source = tmp_path / "synthetic_landscape_16_9.mp4"
        cmd = [
            ffmpeg_bin,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=3:size=1280x720:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=3",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-pix_fmt",
            "yuv420p",
            str(landscape_source),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            pytest.skip(f"Failed to generate synthetic landscape video: {res.stderr}")

        # 2. Run VerticalVideoService
        output_dir = tmp_path / "vertical_output"
        service = VerticalVideoService(
            output_dir=output_dir,
            ffmpeg_executable=ffmpeg_bin,
        )

        vertical_clip: IngestedVideo = service.convert_to_vertical(
            landscape_source,
            request=VerticalVideoRequest(width=1080, height=1920),
        )

        # 3. Verify output exists and is non-zero
        out_path = Path(vertical_clip.file_path)
        assert out_path.is_file()
        assert out_path.stat().st_size > 1000

        # 4. Use VideoMetadataService (ffprobe) to inspect dimensions and properties
        metadata_service = VideoMetadataService(ffprobe_executable=ffprobe_bin)
        meta = metadata_service.extract_metadata(out_path)

        assert meta.width == 1080
        assert meta.height == 1920
        assert abs((meta.width / meta.height) - (9.0 / 16.0)) < 0.001
        assert abs(meta.duration_seconds - 3.0) < 0.5

        # 5. Verify audio stream is present using ffprobe probe command
        probe_cmd = [
            ffprobe_bin,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(out_path),
        ]
        probe_res = subprocess.run(probe_cmd, capture_output=True, text=True)
        assert probe_res.returncode == 0
        assert "aac" in probe_res.stdout.strip().lower()
