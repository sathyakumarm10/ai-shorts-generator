"""End-to-End integration test for the full ShortsGenerationService pipeline.

Runs real FFmpeg clipping, real vertical 9:16 conversion, real caption burn-in,
and validates the final 1080x1920 MP4 short output using ffprobe.
Uses a deterministic TranscriptionProvider mock to avoid redundant Whisper weight downloads.
"""

from pathlib import Path
import shutil
import subprocess
import pytest

from app.models import IngestedVideo, TimestampedTranscript, TranscriptSegment, VideoSource, VideoSourceType
from app.services.caption_burn_service import CaptionBurnService
from app.services.caption_service import CaptionService
from app.services.highlight_clip_service import HighlightClipService
from app.services.highlight_scoring_service import HighlightScoringService
from app.services.shorts_generation_service import ShortsGenerationService
from app.services.transcription_service import TranscriptionProvider, TranscriptionService
from app.services.vertical_video_service import VerticalVideoService
from app.services.video_clip_service import VideoClipService
from app.services.video_ingestion_service import VideoIngestionService
from app.services.video_metadata_service import VideoMetadataService


class DeterministicMockTranscriptionProvider(TranscriptionProvider):
    """Deterministic mock transcription provider for fast CI integration testing."""

    def __init__(self, transcript: TimestampedTranscript) -> None:
        self._transcript = transcript

    def transcribe(self, audio_or_video_path: Path) -> TimestampedTranscript:
        return self._transcript


class TestShortsGenerationRealIntegration:
    def test_full_pipeline_real_ffmpeg_execution(self, tmp_path: Path):
        """Run full end-to-end shorts pipeline using real FFmpeg rendering and ffprobe validation."""
        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
        ffprobe_bin = shutil.which("ffprobe") or "ffprobe"

        if not shutil.which(ffmpeg_bin) or not shutil.which(ffprobe_bin):
            pytest.skip("FFmpeg and/or ffprobe are not available on the system.")

        # 1. Create a 70-second synthetic landscape source video (1280x720) with audio
        source_video_path = tmp_path / "full_pipeline_source_70s.mp4"
        cmd = [
            ffmpeg_bin,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=70:size=1280x720:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=70",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-pix_fmt",
            "yuv420p",
            str(source_video_path),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            pytest.skip(f"Failed to generate synthetic source video: {res.stderr}")

        # 2. Build synthetic transcript with a high-scoring hook section (15.0s to 50.0s)
        transcript = TimestampedTranscript(
            segments=[
                TranscriptSegment(
                    start_seconds=0.0,
                    end_seconds=15.0,
                    text="Welcome to our routine channel update.",
                ),
                TranscriptSegment(
                    start_seconds=15.0,
                    end_seconds=50.0,
                    text="Here's why you won't believe this shocking secret! We increased sales by 85% in 30 days.",
                ),
                TranscriptSegment(
                    start_seconds=50.0,
                    end_seconds=70.0,
                    text="Thank you for watching and remember to subscribe.",
                ),
            ]
        )

        # 3. Instantiate real pipeline services (using deterministic mock transcription provider)
        ingestion_service = VideoIngestionService(download_dir=tmp_path / "ingested")
        ingestion_service.ingest = lambda source: IngestedVideo(file_path=str(source_video_path))
        metadata_service = VideoMetadataService(ffprobe_executable=ffprobe_bin)
        transcription_service = TranscriptionService(
            provider=DeterministicMockTranscriptionProvider(transcript),
            ffmpeg_executable=ffmpeg_bin,
        )
        highlight_scoring_service = HighlightScoringService()
        video_clip_service = VideoClipService(
            output_dir=tmp_path / "raw_clips",
            ffmpeg_executable=ffmpeg_bin,
        )
        highlight_clip_service = HighlightClipService(video_clip_service=video_clip_service)
        vertical_video_service = VerticalVideoService(
            output_dir=tmp_path / "vertical_shorts",
            ffmpeg_executable=ffmpeg_bin,
        )
        caption_service = CaptionService()
        caption_burn_service = CaptionBurnService(
            output_dir=tmp_path / "captioned_shorts",
            ffmpeg_executable=ffmpeg_bin,
            caption_service=caption_service,
        )

        pipeline_service = ShortsGenerationService(
            ingestion_service=ingestion_service,
            metadata_service=metadata_service,
            transcription_service=transcription_service,
            highlight_scoring_service=highlight_scoring_service,
            highlight_clip_service=highlight_clip_service,
            vertical_video_service=vertical_video_service,
            caption_service=caption_service,
            caption_burn_service=caption_burn_service,
        )

        # 4. Execute pipeline
        source = VideoSource(type=VideoSourceType.UPLOAD, location=str(source_video_path))
        result = pipeline_service.generate(
            source=source,
            clip_duration_seconds=35.0,
            number_of_clips=1,
            include_captions=True,
        )

        # 5. Verify results structure and rendered file properties
        assert len(result.generated_shorts) == 1
        short = result.generated_shorts[0]

        assert short.index == 1
        assert short.candidate.start_seconds == 15.0
        assert short.candidate.end_seconds == 50.0

        final_path = Path(short.final_file_path)
        assert final_path.is_file()
        assert final_path.stat().st_size > 1000

        # 6. Verify final video metadata using ffprobe
        meta = metadata_service.extract_metadata(final_path)
        assert meta.width == 1080
        assert meta.height == 1920
        assert abs((meta.width / meta.height) - (9.0 / 16.0)) < 0.001
        assert abs(meta.duration_seconds - 35.0) < 1.0

        # 7. Verify audio stream is present
        probe_audio = subprocess.run(
            [
                ffprobe_bin,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(final_path),
            ],
            capture_output=True,
            text=True,
        )
        assert probe_audio.returncode == 0
        assert "aac" in probe_audio.stdout.strip().lower()
