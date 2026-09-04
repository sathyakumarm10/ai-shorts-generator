"""Unit tests for ShortsGenerationService and related orchestration models.

These tests verify model validations, stage orchestration, parameter handling,
relative caption timestamp computation, and error propagation using mock services.
"""

from pathlib import Path
from unittest.mock import MagicMock
import pytest
from pydantic import ValidationError

from app.models import (
    GeneratedHighlightClip,
    GeneratedShort,
    HighlightCandidate,
    HighlightScore,
    IngestedVideo,
    ShortsGenerationRequest,
    ShortsGenerationResult,
    TimestampedTranscript,
    TranscriptSegment,
    VideoMetadata,
    VideoSource,
    VideoSourceType,
)
from app.services.shorts_generation_service import ShortsGenerationError, ShortsGenerationService
from app.services.video_ingestion_service import VideoIngestionError


# ---------------------------------------------------------------------------
# Test Helpers & Fixtures
# ---------------------------------------------------------------------------


def make_test_candidate(start: float = 10.0, end: float = 40.0, text: str = "Test candidate text.") -> HighlightCandidate:
    dur = round(end - start, 3)
    return HighlightCandidate(
        start_seconds=start,
        end_seconds=end,
        duration_seconds=dur,
        text=text,
        score=HighlightScore(
            overall=0.85,
            hook=0.8,
            emotion=0.8,
            curiosity=0.8,
            information_density=0.8,
        ),
    )


# ---------------------------------------------------------------------------
# Model Validation Tests
# ---------------------------------------------------------------------------


class TestShortsGenerationModels:
    def test_valid_shorts_generation_request_defaults(self):
        source = VideoSource(type=VideoSourceType.UPLOAD, location="sample.mp4")
        req = ShortsGenerationRequest(source=source)

        assert req.clip_duration_seconds == 60.0
        assert req.number_of_clips == 10
        assert req.min_clip_duration == 30.0
        assert req.max_clip_duration == 120.0
        assert req.vertical_width == 1080
        assert req.vertical_height == 1920
        assert req.include_captions is True

    def test_reject_out_of_bounds_clip_duration(self):
        source = VideoSource(type=VideoSourceType.UPLOAD, location="sample.mp4")
        with pytest.raises(ValidationError):
            ShortsGenerationRequest(source=source, clip_duration_seconds=20.0, min_clip_duration=30.0)
        with pytest.raises(ValidationError):
            ShortsGenerationRequest(source=source, clip_duration_seconds=150.0, max_clip_duration=120.0)

    def test_reject_invalid_aspect_ratio_dimensions(self):
        source = VideoSource(type=VideoSourceType.UPLOAD, location="sample.mp4")
        with pytest.raises(ValidationError):
            ShortsGenerationRequest(source=source, vertical_width=1920, vertical_height=1080)

    def test_reject_bool_numerical_parameters(self):
        source = VideoSource(type=VideoSourceType.UPLOAD, location="sample.mp4")
        with pytest.raises(ValidationError):
            ShortsGenerationRequest(source=source, number_of_clips=True)  # type: ignore
        with pytest.raises(ValidationError):
            ShortsGenerationRequest(source=source, clip_duration_seconds=False)  # type: ignore

    def test_valid_generated_short_model(self):
        cand = make_test_candidate()
        short = GeneratedShort(
            index=1,
            candidate=cand,
            source_clip_path="clip.mp4",
            vertical_clip_path="vertical.mp4",
            captioned_clip_path="captioned.mp4",
            final_file_path="captioned.mp4",
        )
        assert short.index == 1
        assert short.final_file_path == "captioned.mp4"

    def test_reject_disordered_or_duplicate_result_indices(self):
        cand = make_test_candidate()
        short1 = GeneratedShort(
            index=1,
            candidate=cand,
            source_clip_path="c1.mp4",
            vertical_clip_path="v1.mp4",
            final_file_path="v1.mp4",
        )
        short2_dup = GeneratedShort(
            index=1,
            candidate=cand,
            source_clip_path="c2.mp4",
            vertical_clip_path="v2.mp4",
            final_file_path="v2.mp4",
        )

        with pytest.raises(ValidationError):
            ShortsGenerationResult(
                source_video=IngestedVideo(file_path="src.mp4"),
                metadata=VideoMetadata(duration_seconds=60.0, width=1920, height=1080, format="mov,mp4", file_size_bytes=1048576),
                transcript=TimestampedTranscript(segments=[]),
                candidates=[cand],
                generated_shorts=[short1, short2_dup],
            )


# ---------------------------------------------------------------------------
# ShortsGenerationService Unit Tests (Mocked Dependencies)
# ---------------------------------------------------------------------------


class TestShortsGenerationServiceUnit:
    @pytest.fixture
    def mock_services(self, tmp_path: Path):
        mock_ingestion = MagicMock()
        mock_metadata = MagicMock()
        mock_transcription = MagicMock()
        mock_scoring = MagicMock()
        mock_clip = MagicMock()
        mock_vertical = MagicMock()
        mock_caption = MagicMock()
        mock_caption_burn = MagicMock()

        # Wire default return values
        mock_ingestion.ingest.return_value = IngestedVideo(file_path=str(tmp_path / "ingested.mp4"))
        mock_metadata.extract_metadata.return_value = VideoMetadata(
            duration_seconds=120.0, width=1920, height=1080, format="mov,mp4", file_size_bytes=1048576
        )
        mock_transcription.transcribe.return_value = TimestampedTranscript(
            segments=[
                TranscriptSegment(start_seconds=0.0, end_seconds=15.0, text="Intro speech."),
                TranscriptSegment(start_seconds=15.0, end_seconds=50.0, text="Amazing secret strategy!"),
                TranscriptSegment(start_seconds=50.0, end_seconds=120.0, text="Closing remarks."),
            ]
        )
        cand1 = make_test_candidate(start=15.0, end=50.0, text="Amazing secret strategy!")
        mock_scoring.generate_candidates.return_value = [cand1]
        mock_clip.generate_clips.return_value = [
            GeneratedHighlightClip(candidate=cand1, file_path=str(tmp_path / "clip_1.mp4"))
        ]
        mock_vertical.convert_to_vertical.return_value = IngestedVideo(
            file_path=str(tmp_path / "vertical_1.mp4")
        )
        mock_caption_burn.burn_captions.return_value = IngestedVideo(
            file_path=str(tmp_path / "captioned_1.mp4")
        )

        service = ShortsGenerationService(
            ingestion_service=mock_ingestion,
            metadata_service=mock_metadata,
            transcription_service=mock_transcription,
            highlight_scoring_service=mock_scoring,
            highlight_clip_service=mock_clip,
            vertical_video_service=mock_vertical,
            caption_service=mock_caption,
            caption_burn_service=mock_caption_burn,
        )

        return service, {
            "ingestion": mock_ingestion,
            "metadata": mock_metadata,
            "transcription": mock_transcription,
            "scoring": mock_scoring,
            "clip": mock_clip,
            "vertical": mock_vertical,
            "caption": mock_caption,
            "caption_burn": mock_caption_burn,
        }

    def test_full_pipeline_orchestration_success(self, mock_services):
        service, mocks = mock_services
        source = VideoSource(type=VideoSourceType.UPLOAD, location="my_video.mp4")

        result = service.generate(source=source, include_captions=True, number_of_clips=1)

        assert isinstance(result, ShortsGenerationResult)
        assert len(result.generated_shorts) == 1

        short = result.generated_shorts[0]
        assert short.index == 1
        assert short.candidate.start_seconds == 15.0
        assert short.candidate.end_seconds == 50.0
        assert "captioned" in short.final_file_path

        # Verify all mocks were invoked
        mocks["ingestion"].ingest.assert_called_once()
        mocks["metadata"].extract_metadata.assert_called_once()
        mocks["transcription"].transcribe.assert_called_once()
        mocks["scoring"].generate_candidates.assert_called_once()
        mocks["clip"].generate_clips.assert_called_once()
        mocks["vertical"].convert_to_vertical.assert_called_once()
        mocks["caption_burn"].burn_captions.assert_called_once()

    def test_pipeline_with_include_captions_false(self, mock_services):
        service, mocks = mock_services
        source = VideoSource(type=VideoSourceType.UPLOAD, location="my_video.mp4")

        result = service.generate(source=source, include_captions=False, number_of_clips=1)

        assert len(result.generated_shorts) == 1
        short = result.generated_shorts[0]
        assert short.captioned_clip_path is None
        assert "vertical" in short.final_file_path
        mocks["caption_burn"].burn_captions.assert_not_called()

    def test_relative_caption_offset_computation(self, mock_services):
        service, mocks = mock_services
        source = VideoSource(type=VideoSourceType.UPLOAD, location="my_video.mp4")

        service.generate(source=source, include_captions=True)

        # Inspect CaptionTrack passed to burn_captions
        burn_call_args = mocks["caption_burn"].burn_captions.call_args
        caption_track = burn_call_args[0][1]

        # The candidate starts at 15.0s, so segment at (15.0, 50.0) becomes (0.0, 35.0) relative
        assert len(caption_track.segments) == 1
        seg = caption_track.segments[0]
        assert seg.start_seconds == 0.0
        assert seg.end_seconds == 35.0
        assert seg.text == "Amazing secret strategy!"

    def test_empty_candidates_returns_empty_shorts_list(self, mock_services):
        service, mocks = mock_services
        mocks["scoring"].generate_candidates.return_value = []
        source = VideoSource(type=VideoSourceType.UPLOAD, location="my_video.mp4")

        result = service.generate(source=source)

        assert result.candidates == []
        assert result.generated_shorts == []
        mocks["clip"].generate_clips.assert_not_called()

    def test_ingestion_error_translated_to_shorts_generation_error(self, mock_services):
        service, mocks = mock_services
        mocks["ingestion"].ingest.side_effect = VideoIngestionError("File not found")
        source = VideoSource(type=VideoSourceType.UPLOAD, location="missing.mp4")

        with pytest.raises(ShortsGenerationError) as exc_info:
            service.generate(source=source)
        assert "ingestion failed" in str(exc_info.value).lower()
