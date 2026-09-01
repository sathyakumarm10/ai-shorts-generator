"""Unit and integration tests for HighlightClipService.

These tests verify model validations, candidate-to-clip conversion, max_clips constraints,
error translation, and end-to-end rendering using FFmpeg.
"""

from pathlib import Path
import pytest
from pydantic import ValidationError

from app.models import (
    GeneratedHighlightClip,
    HighlightCandidate,
    HighlightScore,
    IngestedVideo,
    TimestampedTranscript,
    TranscriptSegment,
    VideoClipRequest,
)
from app.services.highlight_clip_service import HighlightClipError, HighlightClipService
from app.services.highlight_scoring_service import HighlightScoringService
from app.services.video_clip_service import VideoClipError, VideoClipService
from app.services.video_metadata_service import VideoMetadataService


# ---------------------------------------------------------------------------
# Test Helpers & Fixtures
# ---------------------------------------------------------------------------


def make_candidate(
    start: float = 10.0,
    end: float = 40.0,
    text: str = "Test highlight candidate speech.",
    overall: float = 0.8,
) -> HighlightCandidate:
    """Helper to construct a valid HighlightCandidate instance."""
    dur = float(round(end - start, 3))
    return HighlightCandidate(
        start_seconds=start,
        end_seconds=end,
        duration_seconds=dur,
        text=text,
        score=HighlightScore(
            overall=overall,
            hook=overall,
            emotion=overall,
            curiosity=overall,
            information_density=overall,
        ),
    )


class MockVideoClipService(VideoClipService):
    """Mock VideoClipService recording invocations and creating mock output files."""

    def __init__(self, tmp_path: Path, should_fail: bool = False, return_missing_file: bool = False, return_empty_file: bool = False):
        super().__init__(output_dir=tmp_path / "mock_clips")
        self.tmp_path = tmp_path
        self.should_fail = should_fail
        self.return_missing_file = return_missing_file
        self.return_empty_file = return_empty_file
        self.calls: list[tuple[object, VideoClipRequest]] = []

    def create_clip(self, video, clip_request, metadata=None):
        self.calls.append((video, clip_request))
        if self.should_fail:
            raise VideoClipError("Mock FFmpeg rendering error")

        clip_file = self.tmp_path / f"mock_clip_{len(self.calls)}.mp4"
        if self.return_missing_file:
            return IngestedVideo(file_path=str(clip_file))

        if self.return_empty_file:
            clip_file.write_bytes(b"")
        else:
            clip_file.write_bytes(b"mock_mp4_bytes_12345")

        return IngestedVideo(file_path=str(clip_file))


# ---------------------------------------------------------------------------
# GeneratedHighlightClip Model Tests
# ---------------------------------------------------------------------------


class TestGeneratedHighlightClipModel:
    def test_valid_model(self):
        cand = make_candidate()
        clip = GeneratedHighlightClip(candidate=cand, file_path="outputs/clip_1.mp4")
        assert clip.candidate == cand
        assert clip.file_path == "outputs/clip_1.mp4"

    def test_reject_empty_or_whitespace_path(self):
        cand = make_candidate()
        with pytest.raises(ValidationError):
            GeneratedHighlightClip(candidate=cand, file_path="")
        with pytest.raises(ValidationError):
            GeneratedHighlightClip(candidate=cand, file_path="   ")


# ---------------------------------------------------------------------------
# HighlightClipService Unit Tests (Mocked VideoClipService)
# ---------------------------------------------------------------------------


class TestHighlightClipServiceUnit:
    def test_generate_single_clip_success(self, tmp_path: Path):
        source_video = tmp_path / "source.mp4"
        source_video.write_bytes(b"dummy_source")

        mock_clip_svc = MockVideoClipService(tmp_path)
        service = HighlightClipService(video_clip_service=mock_clip_svc)

        candidate = make_candidate(start=12.5, end=42.5, text="First candidate text.")
        clips = service.generate_clips(source_video, [candidate], max_clips=1)

        assert len(clips) == 1
        assert len(mock_clip_svc.calls) == 1
        video_arg, req_arg = mock_clip_svc.calls[0]
        assert req_arg.start_seconds == 12.5
        assert req_arg.duration_seconds == 30.0
        assert clips[0].candidate == candidate
        assert Path(clips[0].file_path).is_file()

    def test_generate_multiple_clips_respects_max_clips_and_ordering(self, tmp_path: Path):
        source_video = tmp_path / "source.mp4"
        source_video.write_bytes(b"dummy_source")

        mock_clip_svc = MockVideoClipService(tmp_path)
        service = HighlightClipService(video_clip_service=mock_clip_svc)

        cand1 = make_candidate(start=0.0, end=30.0, text="Top rank candidate", overall=0.95)
        cand2 = make_candidate(start=40.0, end=75.0, text="Second rank candidate", overall=0.85)
        cand3 = make_candidate(start=80.0, end=115.0, text="Third rank candidate", overall=0.75)

        candidates = [cand1, cand2, cand3]
        clips = service.generate_clips(source_video, candidates, max_clips=2)

        # Only 2 clips should be rendered
        assert len(clips) == 2
        assert len(mock_clip_svc.calls) == 2

        # Order must strictly match candidates input order
        assert clips[0].candidate == cand1
        assert clips[1].candidate == cand2
        assert mock_clip_svc.calls[0][1].start_seconds == 0.0
        assert mock_clip_svc.calls[0][1].duration_seconds == 30.0
        assert mock_clip_svc.calls[1][1].start_seconds == 40.0
        assert mock_clip_svc.calls[1][1].duration_seconds == 35.0

    def test_fewer_candidates_than_max_clips(self, tmp_path: Path):
        source_video = tmp_path / "source.mp4"
        source_video.write_bytes(b"dummy_source")

        mock_clip_svc = MockVideoClipService(tmp_path)
        service = HighlightClipService(video_clip_service=mock_clip_svc)

        candidate = make_candidate(start=10.0, end=40.0)
        clips = service.generate_clips(source_video, [candidate], max_clips=10)

        assert len(clips) == 1
        assert len(mock_clip_svc.calls) == 1

    def test_empty_candidates_returns_empty_list(self, tmp_path: Path):
        source_video = tmp_path / "source.mp4"
        source_video.write_bytes(b"dummy_source")

        mock_clip_svc = MockVideoClipService(tmp_path)
        service = HighlightClipService(video_clip_service=mock_clip_svc)

        clips = service.generate_clips(source_video, [], max_clips=5)
        assert clips == []
        assert len(mock_clip_svc.calls) == 0

    def test_reject_missing_source_video(self, tmp_path: Path):
        service = HighlightClipService(video_clip_service=MockVideoClipService(tmp_path))
        cand = make_candidate()

        with pytest.raises(HighlightClipError) as exc_info:
            service.generate_clips(tmp_path / "non_existent.mp4", [cand])
        assert "not found" in str(exc_info.value).lower()

    def test_reject_invalid_max_clips(self, tmp_path: Path):
        source_video = tmp_path / "source.mp4"
        source_video.write_bytes(b"dummy_source")
        service = HighlightClipService(video_clip_service=MockVideoClipService(tmp_path))
        cand = make_candidate()

        with pytest.raises(HighlightClipError):
            service.generate_clips(source_video, [cand], max_clips=0)
        with pytest.raises(HighlightClipError):
            service.generate_clips(source_video, [cand], max_clips=-5)
        with pytest.raises(HighlightClipError):
            service.generate_clips(source_video, [cand], max_clips=float("nan"))  # type: ignore
        with pytest.raises(HighlightClipError):
            service.generate_clips(source_video, [cand], max_clips=True)  # type: ignore

    def test_video_clip_service_failure_translated_to_highlight_clip_error(self, tmp_path: Path):
        source_video = tmp_path / "source.mp4"
        source_video.write_bytes(b"dummy_source")

        mock_clip_svc = MockVideoClipService(tmp_path, should_fail=True)
        service = HighlightClipService(video_clip_service=mock_clip_svc)
        cand = make_candidate()

        with pytest.raises(HighlightClipError) as exc_info:
            service.generate_clips(source_video, [cand])
        assert "clip generation failed" in str(exc_info.value).lower()

    def test_missing_output_file_raises_highlight_clip_error(self, tmp_path: Path):
        source_video = tmp_path / "source.mp4"
        source_video.write_bytes(b"dummy_source")

        mock_clip_svc = MockVideoClipService(tmp_path, return_missing_file=True)
        service = HighlightClipService(video_clip_service=mock_clip_svc)
        cand = make_candidate()

        with pytest.raises(HighlightClipError) as exc_info:
            service.generate_clips(source_video, [cand])
        assert "does not exist" in str(exc_info.value).lower()

    def test_empty_output_file_raises_highlight_clip_error(self, tmp_path: Path):
        source_video = tmp_path / "source.mp4"
        source_video.write_bytes(b"dummy_source")

        mock_clip_svc = MockVideoClipService(tmp_path, return_empty_file=True)
        service = HighlightClipService(video_clip_service=mock_clip_svc)
        cand = make_candidate()

        with pytest.raises(HighlightClipError) as exc_info:
            service.generate_clips(source_video, [cand])
        assert "empty" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Real End-To-End Integration Test (FFmpeg + Transcript + Highlight + Clips)
# ---------------------------------------------------------------------------


class TestHighlightClipRealIntegration:
    def test_real_highlight_to_video_clip_generation(self, tmp_path: Path):
        """End-to-end test creating synthetic video, scoring transcript, and rendering MP4 clips."""
        import shutil
        import subprocess

        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
        ffprobe_bin = shutil.which("ffprobe") or "ffprobe"

        if not shutil.which(ffmpeg_bin) or not shutil.which(ffprobe_bin):
            pytest.skip("FFmpeg/ffprobe binaries are not available.")

        # 1. Create a 70-second synthetic source video with colored frames and tone
        source_video = tmp_path / "synthetic_source_70s.mp4"
        cmd = [
            ffmpeg_bin,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=70:size=320x240:rate=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=70",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-pix_fmt",
            "yuv420p",
            str(source_video),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            pytest.skip(f"Failed to generate synthetic source video: {res.stderr}")

        # 2. Construct a TimestampedTranscript with a high-value hook section
        transcript = TimestampedTranscript(
            segments=[
                TranscriptSegment(
                    start_seconds=0.0,
                    end_seconds=20.0,
                    text="Welcome to the channel. Today we have a regular discussion.",
                ),
                TranscriptSegment(
                    start_seconds=20.0,
                    end_seconds=55.0,
                    text="Here's why you won't believe this shocking secret! Our team increased performance by 85%.",
                ),
                TranscriptSegment(
                    start_seconds=55.0,
                    end_seconds=70.0,
                    text="Thanks for watching and see you next time.",
                ),
            ]
        )

        # 3. Score transcript and extract candidates
        scoring_service = HighlightScoringService()
        candidates = scoring_service.generate_candidates(
            transcript, min_duration=30.0, max_duration=40.0, target_duration=35.0
        )
        assert len(candidates) >= 1

        # 4. Render candidate clips using real VideoClipService and HighlightClipService
        output_clips_dir = tmp_path / "rendered_highlight_clips"
        video_clip_service = VideoClipService(output_dir=output_clips_dir)
        highlight_clip_service = HighlightClipService(video_clip_service=video_clip_service)

        generated_clips = highlight_clip_service.generate_clips(
            video=source_video,
            candidates=candidates,
            max_clips=1,
        )

        # 5. Verify generated clip metadata and actual media file properties
        assert len(generated_clips) == 1
        clip_info = generated_clips[0]
        clip_path = Path(clip_info.file_path)

        assert clip_path.is_file()
        assert clip_path.stat().st_size > 1000

        # 6. Verify duration with ffprobe via VideoMetadataService
        metadata_service = VideoMetadataService(ffprobe_executable=ffprobe_bin)
        clip_metadata = metadata_service.extract_metadata(clip_path)

        assert clip_metadata.duration_seconds > 0
        expected_dur = clip_info.candidate.duration_seconds
        assert abs(clip_metadata.duration_seconds - expected_dur) < 2.0, (
            f"Rendered clip duration ({clip_metadata.duration_seconds}s) differed from candidate ({expected_dur}s)"
        )
