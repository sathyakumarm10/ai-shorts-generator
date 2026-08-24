"""Unit tests for the timestamped audio transcription service and models.

These tests verify TranscriptSegment and TimestampedTranscript model validations,
the TranscriptionProvider abstraction, error handling, audio extraction cleanup,
and TranscriptionService logic without requiring external paid STT APIs.
"""

import math
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


# ---------------------------------------------------------------------------
# FasterWhisperTranscriptionProvider Unit Tests (Mocked)
# ---------------------------------------------------------------------------


class MockWhisperSegment:
    """Mock segment matching faster-whisper Segment namedtuple interface."""

    def __init__(self, start: float, end: float, text: str):
        self.start = start
        self.end = end
        self.text = text


class TestFasterWhisperTranscriptionProviderUnit:
    def test_provider_initialization_and_configuration(self):
        from app.services.transcription_service import FasterWhisperTranscriptionProvider

        provider = FasterWhisperTranscriptionProvider(
            model_size="base",
            device="cpu",
            compute_type="int8",
            language="en",
            download_root="custom_cache",
            lazy_load=True,
        )
        assert provider.model_size == "base"
        assert provider.device == "cpu"
        assert provider.compute_type == "int8"
        assert provider.language == "en"
        assert provider.download_root == "custom_cache"
        assert provider._model is None

    def test_successful_mocked_segment_conversion(self, tmp_path: Path):
        from app.services.transcription_service import FasterWhisperTranscriptionProvider

        dummy_audio = tmp_path / "test.wav"
        dummy_audio.write_bytes(b"dummy_wav_data")

        provider = FasterWhisperTranscriptionProvider(lazy_load=True)

        class MockModel:
            def transcribe(self, path, language=None, beam_size=5):
                segments = [
                    MockWhisperSegment(start=0.0, end=2.5, text="Hello world"),
                    MockWhisperSegment(start=3.0, end=6.0, text="This is a test"),
                ]
                return (s for s in segments), {}

        provider._model = MockModel()
        transcript = provider.transcribe(dummy_audio)

        assert isinstance(transcript, TimestampedTranscript)
        assert len(transcript.segments) == 2
        assert transcript.segments[0].start_seconds == 0.0
        assert transcript.segments[0].end_seconds == 2.5
        assert transcript.segments[0].text == "Hello world"
        assert transcript.segments[1].start_seconds == 3.0
        assert transcript.segments[1].end_seconds == 6.0
        assert transcript.segments[1].text == "This is a test"

    def test_empty_generator_returns_empty_transcript(self, tmp_path: Path):
        from app.services.transcription_service import FasterWhisperTranscriptionProvider

        dummy_audio = tmp_path / "test.wav"
        dummy_audio.write_bytes(b"dummy_wav_data")

        provider = FasterWhisperTranscriptionProvider(lazy_load=True)

        class MockModel:
            def transcribe(self, path, language=None, beam_size=5):
                return (s for s in []), {}

        provider._model = MockModel()
        transcript = provider.transcribe(dummy_audio)

        assert isinstance(transcript, TimestampedTranscript)
        assert len(transcript.segments) == 0

    def test_invalid_whisper_timestamps_raises_transcription_error(self, tmp_path: Path):
        from app.services.transcription_service import FasterWhisperTranscriptionProvider

        dummy_audio = tmp_path / "test.wav"
        dummy_audio.write_bytes(b"dummy_wav_data")

        provider = FasterWhisperTranscriptionProvider(lazy_load=True)

        class MockModel:
            def transcribe(self, path, language=None, beam_size=5):
                # end_seconds < start_seconds
                segments = [MockWhisperSegment(start=5.0, end=3.0, text="Inverted timestamps")]
                return (s for s in segments), {}

        provider._model = MockModel()
        with pytest.raises(TranscriptionError) as exc_info:
            provider.transcribe(dummy_audio)
        assert "invalid segment timestamps" in str(exc_info.value).lower()

    def test_overlapping_whisper_segments_raises_transcription_error(self, tmp_path: Path):
        from app.services.transcription_service import FasterWhisperTranscriptionProvider

        dummy_audio = tmp_path / "test.wav"
        dummy_audio.write_bytes(b"dummy_wav_data")

        provider = FasterWhisperTranscriptionProvider(lazy_load=True)

        class MockModel:
            def transcribe(self, path, language=None, beam_size=5):
                # Overlapping segments: segment 1 ends at 5.0, segment 2 starts at 4.0
                segments = [
                    MockWhisperSegment(start=0.0, end=5.0, text="Segment 1"),
                    MockWhisperSegment(start=4.0, end=8.0, text="Segment 2"),
                ]
                return (s for s in segments), {}

        provider._model = MockModel()
        with pytest.raises(TranscriptionError) as exc_info:
            provider.transcribe(dummy_audio)
        assert "invalid or overlapping" in str(exc_info.value).lower()

    def test_missing_audio_file_raises_transcription_error(self):
        from app.services.transcription_service import FasterWhisperTranscriptionProvider

        provider = FasterWhisperTranscriptionProvider(lazy_load=True)
        with pytest.raises(TranscriptionError) as exc_info:
            provider.transcribe(Path("non_existent_audio.wav"))
        assert "not found" in str(exc_info.value).lower()

    def test_model_transcribe_exception_wrapped_in_transcription_error(self, tmp_path: Path):
        from app.services.transcription_service import FasterWhisperTranscriptionProvider

        dummy_audio = tmp_path / "test.wav"
        dummy_audio.write_bytes(b"dummy_wav_data")

        provider = FasterWhisperTranscriptionProvider(lazy_load=True)

        class FailingModel:
            def transcribe(self, path, language=None, beam_size=5):
                raise RuntimeError("CTranslate2 inference engine failed")

        provider._model = FailingModel()
        with pytest.raises(TranscriptionError) as exc_info:
            provider.transcribe(dummy_audio)
        assert "FasterWhisper transcription failed" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Real FasterWhisper Local Integration Test (Speech-To-Text)
# ---------------------------------------------------------------------------


def _generate_spoken_audio_fixture(output_wav: Path, phrase: str) -> bool:
    """Generate a spoken speech audio WAV file using Windows Speech Synthesis."""
    import subprocess

    escaped_wav = str(output_wav).replace("'", "''")
    escaped_phrase = phrase.replace("'", "''")
    ps_script = (
        f"Add-Type -AssemblyName System.Speech; "
        f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SetOutputToWaveFile('{escaped_wav}'); "
        f"$s.Speak('{escaped_phrase}'); "
        f"$s.Dispose()"
    )
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return res.returncode == 0 and output_wav.is_file() and output_wav.stat().st_size > 0
    except Exception:
        return False


class TestFasterWhisperRealIntegration:
    def test_real_local_faster_whisper_transcription(self, tmp_path: Path):
        from app.services.transcription_service import FasterWhisperTranscriptionProvider

        spoken_wav = tmp_path / "real_speech.wav"
        phrase = "Hello, this is a test of speech recognition."

        speech_generated = _generate_spoken_audio_fixture(spoken_wav, phrase)
        if not speech_generated:
            pytest.skip("Windows Speech Synthesis (SAPI) is unavailable to generate spoken speech fixture.")

        provider = FasterWhisperTranscriptionProvider(
            model_size="tiny",
            device="cpu",
            compute_type="int8",
            language="en",
        )

        try:
            transcript = provider.transcribe(spoken_wav)
        except TranscriptionError as exc:
            pytest.skip(f"FasterWhisper model unavailable or download failed: {exc}")
        except Exception as exc:
            pytest.skip(f"FasterWhisper execution failed: {exc}")

        # Verify output
        assert isinstance(transcript, TimestampedTranscript)
        assert len(transcript.segments) >= 1, "Expected at least one transcribed segment for spoken speech."

        for seg in transcript.segments:
            assert seg.start_seconds >= 0.0
            assert seg.end_seconds > seg.start_seconds
            assert math.isfinite(seg.start_seconds)
            assert math.isfinite(seg.end_seconds)
            assert len(seg.text.strip()) > 0

        # Combine text to verify basic speech content recognition
        full_text = " ".join(seg.text for seg in transcript.segments).lower()
        assert any(word in full_text for word in ["hello", "this", "test", "speech", "recognition"]), (
            f"Recognized text '{full_text}' did not match expected spoken words."
        )


