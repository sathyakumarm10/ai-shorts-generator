"""Unit tests for the timestamped audio transcription service and models.

These tests verify TranscriptSegment and TimestampedTranscript model validations,
the TranscriptionProvider abstraction, error handling, audio extraction cleanup,
and TranscriptionService logic without requiring external paid STT APIs.
"""

from pathlib import Path
import pytest
from pydantic import ValidationError

from app.models import IngestedVideo, TimestampedTranscript, TranscriptSegment
from app.services.transcription_service import (
    PlaceholderTranscriptionProvider,
    TranscriptionError,
    TranscriptionProvider,
    TranscriptionService,
)


# ---------------------------------------------------------------------------
# Mock Transcription Provider for Tests
# ---------------------------------------------------------------------------


class MockTranscriptionProvider(TranscriptionProvider):
    """Test provider that returns predefined transcript segments or raises an exception."""

    def __init__(self, transcript: TimestampedTranscript | None = None, should_fail: bool = False):
        self.transcript = transcript or TimestampedTranscript(
            segments=[
                TranscriptSegment(
                    start_seconds=0.0,
                    end_seconds=4.5,
                    text="Welcome to the video presentation.",
                ),
                TranscriptSegment(
                    start_seconds=5.0,
                    end_seconds=12.2,
                    text="Today we will discuss building automated Shorts.",
                ),
            ]
        )
        self.should_fail = should_fail
        self.last_transcribed_path: Path | None = None

    def transcribe(self, audio_or_video_path: Path) -> TimestampedTranscript:
        self.last_transcribed_path = audio_or_video_path
        if self.should_fail:
            raise RuntimeError("Mock STT provider encountered an internal failure.")
        return self.transcript


# ---------------------------------------------------------------------------
# TranscriptSegment Model Tests
# ---------------------------------------------------------------------------


class TestTranscriptSegmentModel:
    def test_valid_transcript_segment(self):
        seg = TranscriptSegment(
            start_seconds=1.5,
            end_seconds=4.8,
            text="Hello world",
        )
        assert seg.start_seconds == 1.5
        assert seg.end_seconds == 4.8
        assert seg.text == "Hello world"

    def test_reject_start_greater_than_or_equal_to_end(self):
        with pytest.raises(ValidationError):
            TranscriptSegment(start_seconds=5.0, end_seconds=5.0, text="Equal timestamps")
        with pytest.raises(ValidationError):
            TranscriptSegment(start_seconds=6.0, end_seconds=5.0, text="Inverted timestamps")

    def test_reject_negative_start_seconds(self):
        with pytest.raises(ValidationError):
            TranscriptSegment(start_seconds=-0.5, end_seconds=3.0, text="Negative start")

    def test_reject_empty_or_whitespace_text(self):
        with pytest.raises(ValidationError):
            TranscriptSegment(start_seconds=0.0, end_seconds=2.0, text="")
        with pytest.raises(ValidationError):
            TranscriptSegment(start_seconds=0.0, end_seconds=2.0, text="   \t\n  ")

    def test_reject_nan_or_infinite_timestamps(self):
        with pytest.raises(ValidationError):
            TranscriptSegment(start_seconds=float("nan"), end_seconds=5.0, text="NaN start")
        with pytest.raises(ValidationError):
            TranscriptSegment(start_seconds=0.0, end_seconds=float("nan"), text="NaN end")
        with pytest.raises(ValidationError):
            TranscriptSegment(start_seconds=0.0, end_seconds=float("inf"), text="Inf end")
        with pytest.raises(ValidationError):
            TranscriptSegment(start_seconds=float("inf"), end_seconds=10.0, text="Inf start")


# ---------------------------------------------------------------------------
# TimestampedTranscript Model Tests
# ---------------------------------------------------------------------------


class TestTimestampedTranscriptModel:
    def test_valid_empty_transcript(self):
        transcript = TimestampedTranscript(segments=[])
        assert transcript.segments == []

    def test_valid_chronological_transcript_with_gaps(self):
        transcript = TimestampedTranscript(
            segments=[
                TranscriptSegment(start_seconds=0.0, end_seconds=3.0, text="Segment 1"),
                TranscriptSegment(start_seconds=4.0, end_seconds=7.5, text="Segment 2"),
                TranscriptSegment(start_seconds=7.5, end_seconds=10.0, text="Segment 3 (contiguous)"),
            ]
        )
        assert len(transcript.segments) == 3

    def test_reject_unordered_segments(self):
        with pytest.raises(ValidationError) as exc_info:
            TimestampedTranscript(
                segments=[
                    TranscriptSegment(start_seconds=5.0, end_seconds=8.0, text="Later segment first"),
                    TranscriptSegment(start_seconds=1.0, end_seconds=3.0, text="Earlier segment second"),
                ]
            )
        assert "chronologically ordered" in str(exc_info.value)

    def test_reject_overlapping_segments(self):
        with pytest.raises(ValidationError) as exc_info:
            TimestampedTranscript(
                segments=[
                    TranscriptSegment(start_seconds=0.0, end_seconds=5.0, text="First segment"),
                    TranscriptSegment(start_seconds=4.0, end_seconds=8.0, text="Overlapping second segment"),
                ]
            )
        assert "must not overlap" in str(exc_info.value)


# ---------------------------------------------------------------------------
# TranscriptionService & Provider Tests
# ---------------------------------------------------------------------------


class TestTranscriptionService:
    def test_placeholder_provider_raises_transcription_error(self, tmp_path: Path):
        fake_video = tmp_path / "video.mp4"
        fake_video.write_bytes(b"mock_video_bytes")

        service = TranscriptionService()
        assert isinstance(service.provider, PlaceholderTranscriptionProvider)

        with pytest.raises(TranscriptionError) as exc_info:
            service.transcribe(fake_video, extract_audio_first=False)
        assert "No speech-to-text engine is currently active" in str(exc_info.value)

    def test_transcribe_missing_video_raises_transcription_error(self):
        service = TranscriptionService()
        missing_path = Path("non_existent_video_path.mp4")

        with pytest.raises(TranscriptionError) as exc_info:
            service.transcribe(missing_path)
        assert "not found" in str(exc_info.value).lower()

    def test_transcribe_with_mock_provider_success(self, tmp_path: Path):
        fake_video = tmp_path / "sample.mp4"
        fake_video.write_bytes(b"mock_video_bytes")

        mock_provider = MockTranscriptionProvider()
        service = TranscriptionService(provider=mock_provider)

        transcript = service.transcribe(fake_video, extract_audio_first=False)
        assert len(transcript.segments) == 2
        assert transcript.segments[0].text == "Welcome to the video presentation."
        assert mock_provider.last_transcribed_path == fake_video

    def test_transcribe_with_ingested_video_model(self, tmp_path: Path):
        fake_video = tmp_path / "sample.mp4"
        fake_video.write_bytes(b"mock_video_bytes")

        ingested = IngestedVideo(file_path=str(fake_video))
        mock_provider = MockTranscriptionProvider()
        service = TranscriptionService(provider=mock_provider)

        transcript = service.transcribe(ingested, extract_audio_first=False)
        assert len(transcript.segments) == 2
        assert mock_provider.last_transcribed_path == fake_video

    def test_transcribe_provider_failure_raises_transcription_error(self, tmp_path: Path):
        fake_video = tmp_path / "sample.mp4"
        fake_video.write_bytes(b"mock_video_bytes")

        failing_provider = MockTranscriptionProvider(should_fail=True)
        service = TranscriptionService(provider=failing_provider)

        with pytest.raises(TranscriptionError) as exc_info:
            service.transcribe(fake_video, extract_audio_first=False)
        assert "Transcription provider failed" in str(exc_info.value)

    def test_invalid_provider_return_type_raises_transcription_error(self, tmp_path: Path):
        fake_video = tmp_path / "sample.mp4"
        fake_video.write_bytes(b"mock_video_bytes")

        class InvalidReturnProvider(TranscriptionProvider):
            def transcribe(self, audio_or_video_path: Path) -> TimestampedTranscript:
                return "NotATranscript"  # type: ignore

        service = TranscriptionService(provider=InvalidReturnProvider())
        with pytest.raises(TranscriptionError) as exc_info:
            service.transcribe(fake_video, extract_audio_first=False)
        assert "invalid transcript type" in str(exc_info.value).lower()

    def test_audio_extraction_missing_ffmpeg(self, tmp_path: Path):
        fake_video = tmp_path / "sample.mp4"
        fake_video.write_bytes(b"mock_video_bytes")
        out_wav = tmp_path / "out.wav"

        service = TranscriptionService(ffmpeg_executable="non_existent_ffmpeg_executable_xyz")
        with pytest.raises(TranscriptionError) as exc_info:
            service.extract_audio(fake_video, out_wav)
        assert "not found" in str(exc_info.value).lower()

    def test_extract_audio_real_ffmpeg_and_cleanup(self, tmp_path: Path):
        import shutil
        import subprocess

        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
        test_video = tmp_path / "synthetic_test.mp4"

        # Generate a minimal 1-second synthetic test video with sine audio
        cmd = [
            ffmpeg_bin,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=1",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:d=1",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-pix_fmt",
            "yuv420p",
            str(test_video),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            pytest.skip(f"FFmpeg synthetic test video generation failed: {res.stderr}")

        audio_path_during_call: list[Path] = []

        class RecordingMockProvider(TranscriptionProvider):
            def transcribe(self, audio_or_video_path: Path) -> TimestampedTranscript:
                audio_path_during_call.append(audio_or_video_path)
                assert audio_or_video_path.is_file()
                assert audio_or_video_path.stat().st_size > 0
                return TimestampedTranscript(
                    segments=[TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="Beep")]
                )

        service = TranscriptionService(provider=RecordingMockProvider())
        transcript = service.transcribe(test_video, extract_audio_first=True)

        assert len(transcript.segments) == 1
        assert len(audio_path_during_call) == 1
        # Verify temporary audio file and its temp directory are cleaned up after transcription
        temp_audio_file = audio_path_during_call[0]
        assert not temp_audio_file.exists(), "Temporary audio file was not cleaned up!"

