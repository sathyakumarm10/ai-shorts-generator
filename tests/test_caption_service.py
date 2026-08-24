"""Unit tests for CaptionService, CaptionSegment, and CaptionTrack models.

These tests verify timestamp validation, non-overlapping track enforcement,
transcript conversion, SRT string formatting, and Unicode subtitle handling.
"""

from pathlib import Path
import pytest
from pydantic import ValidationError

from app.models import CaptionSegment, CaptionTrack, TimestampedTranscript, TranscriptSegment
from app.services.caption_service import CaptionService, CaptionServiceError, format_srt_timestamp


# ---------------------------------------------------------------------------
# CaptionSegment & CaptionTrack Model Tests
# ---------------------------------------------------------------------------


class TestCaptionModels:
    def test_valid_caption_segment(self):
        seg = CaptionSegment(start_seconds=1.5, end_seconds=4.8, text="Hello world")
        assert seg.start_seconds == 1.5
        assert seg.end_seconds == 4.8
        assert seg.text == "Hello world"

    def test_reject_negative_timestamps(self):
        with pytest.raises(ValidationError):
            CaptionSegment(start_seconds=-0.5, end_seconds=3.0, text="Negative start")

    def test_reject_end_less_than_or_equal_to_start(self):
        with pytest.raises(ValidationError):
            CaptionSegment(start_seconds=5.0, end_seconds=5.0, text="Equal timestamps")
        with pytest.raises(ValidationError):
            CaptionSegment(start_seconds=6.0, end_seconds=5.0, text="Inverted timestamps")

    def test_reject_nan_or_infinite_timestamps(self):
        with pytest.raises(ValidationError):
            CaptionSegment(start_seconds=float("nan"), end_seconds=5.0, text="NaN start")
        with pytest.raises(ValidationError):
            CaptionSegment(start_seconds=0.0, end_seconds=float("nan"), text="NaN end")
        with pytest.raises(ValidationError):
            CaptionSegment(start_seconds=0.0, end_seconds=float("inf"), text="Inf end")
        with pytest.raises(ValidationError):
            CaptionSegment(start_seconds=float("inf"), end_seconds=10.0, text="Inf start")

    def test_reject_empty_or_whitespace_text(self):
        with pytest.raises(ValidationError):
            CaptionSegment(start_seconds=0.0, end_seconds=2.0, text="")
        with pytest.raises(ValidationError):
            CaptionSegment(start_seconds=0.0, end_seconds=2.0, text="   \t\n  ")

    def test_empty_caption_track_allowed(self):
        track = CaptionTrack(segments=[])
        assert track.segments == []

    def test_valid_chronological_caption_track(self):
        track = CaptionTrack(
            segments=[
                CaptionSegment(start_seconds=0.0, end_seconds=3.0, text="First"),
                CaptionSegment(start_seconds=3.5, end_seconds=6.0, text="Second (with gap)"),
                CaptionSegment(start_seconds=6.0, end_seconds=9.0, text="Third (contiguous)"),
            ]
        )
        assert len(track.segments) == 3

    def test_reject_disordered_caption_track(self):
        with pytest.raises(ValidationError):
            CaptionTrack(
                segments=[
                    CaptionSegment(start_seconds=5.0, end_seconds=8.0, text="Later first"),
                    CaptionSegment(start_seconds=1.0, end_seconds=3.0, text="Earlier second"),
                ]
            )

    def test_reject_overlapping_caption_track(self):
        with pytest.raises(ValidationError):
            CaptionTrack(
                segments=[
                    CaptionSegment(start_seconds=0.0, end_seconds=5.0, text="First"),
                    CaptionSegment(start_seconds=4.0, end_seconds=8.0, text="Overlapping"),
                ]
            )


# ---------------------------------------------------------------------------
# CaptionService Functionality Tests
# ---------------------------------------------------------------------------


class TestCaptionService:
    def test_format_srt_timestamp_conversions(self):
        assert format_srt_timestamp(0.0) == "00:00:00,000"
        assert format_srt_timestamp(1.5) == "00:00:01,500"
        assert format_srt_timestamp(65.123) == "00:01:05,123"
        assert format_srt_timestamp(3661.045) == "01:01:01,045"

    def test_from_transcript_converts_segments_and_preserves_timestamps(self):
        service = CaptionService()
        transcript = TimestampedTranscript(
            segments=[
                TranscriptSegment(start_seconds=0.0, end_seconds=4.2, text="  Welcome to the show.  "),
                TranscriptSegment(start_seconds=4.5, end_seconds=8.9, text="Today we discuss Shorts.\n"),
            ]
        )

        track = service.from_transcript(transcript)
        assert isinstance(track, CaptionTrack)
        assert len(track.segments) == 2

        assert track.segments[0].start_seconds == 0.0
        assert track.segments[0].end_seconds == 4.2
        assert track.segments[0].text == "Welcome to the show."

        assert track.segments[1].start_seconds == 4.5
        assert track.segments[1].end_seconds == 8.9
        assert track.segments[1].text == "Today we discuss Shorts."

    def test_from_transcript_rejects_invalid_type(self):
        service = CaptionService()
        with pytest.raises(CaptionServiceError):
            service.from_transcript("not_a_transcript")  # type: ignore

    def test_to_srt_empty_track(self):
        service = CaptionService()
        track = CaptionTrack(segments=[])
        assert service.to_srt(track) == ""

    def test_to_srt_multiple_segments_and_numbering(self):
        service = CaptionService()
        track = CaptionTrack(
            segments=[
                CaptionSegment(start_seconds=0.0, end_seconds=2.5, text="Hello world"),
                CaptionSegment(start_seconds=3.0, end_seconds=7.25, text="Second subtitle line"),
            ]
        )
        srt_text = service.to_srt(track)

        expected = (
            "1\n"
            "00:00:00,000 --> 00:00:02,500\n"
            "Hello world\n\n"
            "2\n"
            "00:00:03,000 --> 00:00:07,250\n"
            "Second subtitle line\n\n"
        )
        assert srt_text == expected

    def test_to_srt_unicode_handling(self):
        service = CaptionService()
        track = CaptionTrack(
            segments=[
                CaptionSegment(start_seconds=0.0, end_seconds=3.0, text="✨ Éxito en Español y 日本語 🚀"),
            ]
        )
        srt_text = service.to_srt(track)
        assert "✨ Éxito en Español y 日本語 🚀" in srt_text

    def test_write_srt_creates_file(self, tmp_path: Path):
        service = CaptionService()
        track = CaptionTrack(
            segments=[
                CaptionSegment(start_seconds=0.0, end_seconds=5.0, text="Written to disk test"),
            ]
        )
        out_file = tmp_path / "subtitles_dir" / "test.srt"
        result_path = service.write_srt(track, out_file)

        assert result_path.is_file()
        assert "Written to disk test" in result_path.read_text(encoding="utf-8")
