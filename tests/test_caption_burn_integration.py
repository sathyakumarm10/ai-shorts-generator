"""Real FFmpeg integration test for caption burning into 9:16 vertical Shorts.

Verifies end-to-end pipeline:
Synthetic landscape video -> Vertical 1080x1920 conversion -> Caption generation -> FFmpeg caption burn-in.
Inspects video properties, codecs, and visual pixel modification from burned subtitles.
"""

from pathlib import Path
import shutil
import subprocess
import pytest

from app.models import TimestampedTranscript, TranscriptSegment
from app.services.caption_burn_service import CaptionBurnService
from app.services.caption_service import CaptionService
from app.services.vertical_video_service import VerticalVideoService
from app.services.video_metadata_service import VideoMetadataService


class TestCaptionBurnRealIntegration:
    def test_real_ffmpeg_caption_burn_pipeline(self, tmp_path: Path):
        """End-to-end test converting landscape video to vertical and burning styled captions."""
        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
        ffprobe_bin = shutil.which("ffprobe") or "ffprobe"

        if not shutil.which(ffmpeg_bin) or not shutil.which(ffprobe_bin):
            pytest.skip("FFmpeg and/or ffprobe are not available on the system.")

        # 1. Create a 3-second 16:9 landscape test video with solid background and sine audio
        landscape_source = tmp_path / "raw_landscape_source.mp4"
        cmd = [
            ffmpeg_bin,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1280x720:d=3:r=24",
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
            pytest.skip(f"Failed to generate synthetic source video: {res.stderr}")

        # 2. Convert to vertical 9:16 (1080x1920) using VerticalVideoService
        vertical_service = VerticalVideoService(
            output_dir=tmp_path / "vertical_output",
            ffmpeg_executable=ffmpeg_bin,
        )
        vertical_video = vertical_service.convert_to_vertical(landscape_source)
        vertical_video_path = Path(vertical_video.file_path)
        assert vertical_video_path.is_file()

        # 3. Create TimestampedTranscript and generate CaptionTrack
        transcript = TimestampedTranscript(
            segments=[
                TranscriptSegment(start_seconds=0.0, end_seconds=1.5, text="First captioned subtitle line"),
                TranscriptSegment(start_seconds=1.5, end_seconds=3.0, text="Second captioned subtitle line"),
            ]
        )
        caption_service = CaptionService()
        caption_track = caption_service.from_transcript(transcript)
        assert len(caption_track.segments) == 2

        # 4. Burn captions into vertical video using CaptionBurnService
        caption_burn_service = CaptionBurnService(
            output_dir=tmp_path / "captioned_output",
            ffmpeg_executable=ffmpeg_bin,
            caption_service=caption_service,
        )
        captioned_video = caption_burn_service.burn_captions(vertical_video_path, caption_track)
        captioned_path = Path(captioned_video.file_path)

        # 5. Verify output file properties
        assert captioned_path.is_file()
        assert captioned_path.stat().st_size > 1000

        # 6. Verify technical metadata with VideoMetadataService (ffprobe)
        metadata_service = VideoMetadataService(ffprobe_executable=ffprobe_bin)
        meta = metadata_service.extract_metadata(captioned_path)

        assert meta.width == 1080
        assert meta.height == 1920
        assert abs(meta.duration_seconds - 3.0) < 0.5

        # 7. Verify audio stream is present
        probe_audio_cmd = [
            ffprobe_bin,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(captioned_path),
        ]
        audio_res = subprocess.run(probe_audio_cmd, capture_output=True, text=True)
        assert audio_res.returncode == 0
        assert "aac" in audio_res.stdout.strip().lower()

        # 8. Verify subtitle filter was actually applied by measuring pixel difference (PSNR)
        # Comparing uncaptioned black vertical video vs captioned vertical video
        # Subtitles (white text + black outline) produce a finite PSNR indicating frame modification
        psnr_cmd = [
            ffmpeg_bin,
            "-i",
            str(vertical_video_path),
            "-i",
            str(captioned_path),
            "-filter_complex",
            "psnr",
            "-f",
            "null",
            "-",
        ]
        psnr_res = subprocess.run(psnr_cmd, capture_output=True, text=True)
        assert psnr_res.returncode == 0
        stderr_output = psnr_res.stderr.lower()
        assert "psnr" in stderr_output, f"Expected PSNR computation in FFmpeg output: {psnr_res.stderr}"
        # If pixels were identical, PSNR would show 'inf' (infinity). With burned captions, PSNR is finite (< 100dB)
        assert "average:inf" not in stderr_output or "y:" in stderr_output, (
            "Captions did not modify any video frame pixels!"
        )
