"""Unit tests for the deterministic ClipPlannerService.

These tests verify clip window calculation, duration constraints, non-overlapping
clip generation, edge cases, deterministic outputs, and error handling without
using real video files or invoking external media binaries like FFmpeg.
"""

import math
import pytest
from pydantic import ValidationError

from app.models import PlannedClip, VideoMetadata
from app.services.clip_planner_service import ClipPlannerService, ClipPlanningError


@pytest.fixture
def planner() -> ClipPlannerService:
    """Fixture providing a ClipPlannerService instance."""
    return ClipPlannerService()


def make_metadata(
    duration_seconds: float = 600.0,
    width: int = 1920,
    height: int = 1080,
    format_name: str = "mp4",
    file_size_bytes: int = 1024 * 1024,
) -> VideoMetadata:
    """Helper to construct a valid VideoMetadata object for unit tests."""
    return VideoMetadata(
        duration_seconds=duration_seconds,
        width=width,
        height=height,
        format=format_name,
        file_size_bytes=file_size_bytes,
    )


# ---------------------------------------------------------------------------
# PlannedClip Pydantic Model Unit Tests
# ---------------------------------------------------------------------------


class TestPlannedClipModel:
    def test_valid_planned_clip(self):
        clip = PlannedClip(
            index=1,
            start_seconds=0.0,
            duration_seconds=60.0,
            end_seconds=60.0,
        )
        assert clip.index == 1
        assert clip.start_seconds == 0.0
        assert clip.duration_seconds == 60.0
        assert clip.end_seconds == 60.0

    def test_reject_zero_or_negative_index(self):
        with pytest.raises(ValidationError):
            PlannedClip(index=0, start_seconds=0.0, duration_seconds=60.0, end_seconds=60.0)
        with pytest.raises(ValidationError):
            PlannedClip(index=-1, start_seconds=0.0, duration_seconds=60.0, end_seconds=60.0)

    def test_reject_negative_start_seconds(self):
        with pytest.raises(ValidationError):
            PlannedClip(index=1, start_seconds=-0.1, duration_seconds=60.0, end_seconds=59.9)

    def test_reject_duration_out_of_bounds(self):
        with pytest.raises(ValidationError):
            PlannedClip(index=1, start_seconds=0.0, duration_seconds=29.9, end_seconds=29.9)
        with pytest.raises(ValidationError):
            PlannedClip(index=1, start_seconds=0.0, duration_seconds=120.1, end_seconds=120.1)

    def test_reject_end_seconds_not_greater_than_start(self):
        with pytest.raises(ValidationError):
            PlannedClip(index=1, start_seconds=50.0, duration_seconds=60.0, end_seconds=50.0)
        with pytest.raises(ValidationError):
            PlannedClip(index=1, start_seconds=50.0, duration_seconds=60.0, end_seconds=40.0)

    def test_reject_nan_or_inf_in_model(self):
        with pytest.raises(ValidationError):
            PlannedClip(index=1, start_seconds=float("nan"), duration_seconds=60.0, end_seconds=60.0)
        with pytest.raises(ValidationError):
            PlannedClip(index=1, start_seconds=0.0, duration_seconds=float("inf"), end_seconds=60.0)
        with pytest.raises(ValidationError):
            PlannedClip(index=1, start_seconds=0.0, duration_seconds=60.0, end_seconds=float("inf"))


# ---------------------------------------------------------------------------
# ClipPlannerService Planning Algorithm Tests
# ---------------------------------------------------------------------------


class TestClipPlannerServiceAlgorithm:
    def test_single_clip_placed_at_start(self, planner: ClipPlannerService):
        metadata = make_metadata(duration_seconds=600.0)
        clips = planner.plan_clips(metadata, clip_duration_seconds=60.0, number_of_clips=1)

        assert len(clips) == 1
        clip = clips[0]
        assert clip.index == 1
        assert clip.start_seconds == 0.0
        assert clip.duration_seconds == 60.0
        assert clip.end_seconds == 60.0

    def test_two_clips_distributed(self, planner: ClipPlannerService):
        metadata = make_metadata(duration_seconds=600.0)
        clips = planner.plan_clips(metadata, clip_duration_seconds=60.0, number_of_clips=2)

        assert len(clips) == 2
        assert clips[0].index == 1
        assert clips[0].start_seconds == 0.0
        assert clips[0].end_seconds == 60.0

        assert clips[1].index == 2
        assert clips[1].start_seconds == 540.0
        assert clips[1].end_seconds == 600.0

    def test_five_clips_distributed_evenly(self, planner: ClipPlannerService):
        metadata = make_metadata(duration_seconds=600.0)
        clips = planner.plan_clips(metadata, clip_duration_seconds=60.0, number_of_clips=5)

        assert len(clips) == 5
        # Expected step = (600 - 60) / (5 - 1) = 540 / 4 = 135.0
        expected_starts = [0.0, 135.0, 270.0, 405.0, 540.0]
        for i, clip in enumerate(clips):
            assert clip.index == i + 1
            assert clip.start_seconds == pytest.approx(expected_starts[i], rel=1e-5)
            assert clip.duration_seconds == 60.0
            assert clip.end_seconds == pytest.approx(expected_starts[i] + 60.0, rel=1e-5)
            assert clip.end_seconds <= metadata.duration_seconds

    def test_exact_fit_duration(self, planner: ClipPlannerService):
        # 2 clips of 120s each = 240s total in a 240s video
        metadata = make_metadata(duration_seconds=240.0)
        clips = planner.plan_clips(metadata, clip_duration_seconds=120.0, number_of_clips=2)

        assert len(clips) == 2
        assert clips[0].start_seconds == 0.0
        assert clips[0].end_seconds == 120.0
        assert clips[1].start_seconds == 120.0
        assert clips[1].end_seconds == 240.0

    def test_minimum_clip_duration_boundary_30s(self, planner: ClipPlannerService):
        metadata = make_metadata(duration_seconds=100.0)
        clips = planner.plan_clips(metadata, clip_duration_seconds=30.0, number_of_clips=2)

        assert len(clips) == 2
        assert clips[0].duration_seconds == 30.0
        assert clips[1].duration_seconds == 30.0
        assert clips[0].start_seconds == 0.0
        assert clips[1].start_seconds == 70.0
        assert clips[1].end_seconds == 100.0

    def test_maximum_clip_duration_boundary_120s(self, planner: ClipPlannerService):
        metadata = make_metadata(duration_seconds=300.0)
        clips = planner.plan_clips(metadata, clip_duration_seconds=120.0, number_of_clips=2)

        assert len(clips) == 2
        assert clips[0].duration_seconds == 120.0
        assert clips[1].duration_seconds == 120.0
        assert clips[0].start_seconds == 0.0
        assert clips[0].end_seconds == 120.0
        assert clips[1].start_seconds == 180.0
        assert clips[1].end_seconds == 300.0

    def test_non_overlapping_invariant(self, planner: ClipPlannerService):
        metadata = make_metadata(duration_seconds=1000.0)
        clips = planner.plan_clips(metadata, clip_duration_seconds=45.0, number_of_clips=8)

        assert len(clips) == 8
        for i in range(len(clips) - 1):
            assert clips[i].end_seconds <= clips[i + 1].start_seconds + 1e-6
            assert clips[i].start_seconds >= 0.0
            assert clips[i].end_seconds <= metadata.duration_seconds

    def test_every_clip_ends_within_source_duration(self, planner: ClipPlannerService):
        metadata = make_metadata(duration_seconds=450.5)
        clips = planner.plan_clips(metadata, clip_duration_seconds=75.0, number_of_clips=4)

        for clip in clips:
            assert clip.end_seconds <= metadata.duration_seconds
            assert clip.start_seconds >= 0.0

    def test_deterministic_output(self, planner: ClipPlannerService):
        metadata = make_metadata(duration_seconds=720.0)
        run_one = planner.plan_clips(metadata, clip_duration_seconds=50.0, number_of_clips=6)
        run_two = planner.plan_clips(metadata, clip_duration_seconds=50.0, number_of_clips=6)

        assert len(run_one) == len(run_two)
        for c1, c2 in zip(run_one, run_two):
            assert c1.index == c2.index
            assert c1.start_seconds == c2.start_seconds
            assert c1.duration_seconds == c2.duration_seconds
            assert c1.end_seconds == c2.end_seconds


# ---------------------------------------------------------------------------
# ClipPlannerService Validation & Error Handling Tests
# ---------------------------------------------------------------------------


class TestClipPlannerServiceValidation:
    def test_reject_impossible_clip_combination(self, planner: ClipPlannerService):
        # 2 clips of 120s requires 240s, but video is only 200s
        metadata = make_metadata(duration_seconds=200.0)
        with pytest.raises(ClipPlanningError) as exc_info:
            planner.plan_clips(metadata, clip_duration_seconds=120.0, number_of_clips=2)
        assert "insufficient" in str(exc_info.value).lower() or "cannot fit" in str(exc_info.value).lower()

    def test_reject_zero_clip_count(self, planner: ClipPlannerService):
        metadata = make_metadata(duration_seconds=600.0)
        with pytest.raises(ClipPlanningError):
            planner.plan_clips(metadata, clip_duration_seconds=60.0, number_of_clips=0)

    def test_reject_negative_clip_count(self, planner: ClipPlannerService):
        metadata = make_metadata(duration_seconds=600.0)
        with pytest.raises(ClipPlanningError):
            planner.plan_clips(metadata, clip_duration_seconds=60.0, number_of_clips=-3)

    def test_reject_clip_duration_below_30(self, planner: ClipPlannerService):
        metadata = make_metadata(duration_seconds=600.0)
        with pytest.raises(ClipPlanningError):
            planner.plan_clips(metadata, clip_duration_seconds=29.99, number_of_clips=1)

    def test_reject_clip_duration_above_120(self, planner: ClipPlannerService):
        metadata = make_metadata(duration_seconds=600.0)
        with pytest.raises(ClipPlanningError):
            planner.plan_clips(metadata, clip_duration_seconds=120.01, number_of_clips=1)

    def test_reject_invalid_source_duration(self, planner: ClipPlannerService):
        # Video duration <= 0 or invalid
        with pytest.raises(ValidationError):
            make_metadata(duration_seconds=0.0)
        with pytest.raises(ValidationError):
            make_metadata(duration_seconds=-10.0)

    def test_reject_nan_source_duration(self, planner: ClipPlannerService):
        # Even if bypass Pydantic construction or pass raw object
        metadata = make_metadata(duration_seconds=600.0)
        metadata.duration_seconds = float("nan")
        with pytest.raises(ClipPlanningError):
            planner.plan_clips(metadata, clip_duration_seconds=60.0, number_of_clips=1)

    def test_reject_inf_source_duration(self, planner: ClipPlannerService):
        metadata = make_metadata(duration_seconds=600.0)
        metadata.duration_seconds = float("inf")
        with pytest.raises(ClipPlanningError):
            planner.plan_clips(metadata, clip_duration_seconds=60.0, number_of_clips=1)

    def test_reject_nan_clip_duration(self, planner: ClipPlannerService):
        metadata = make_metadata(duration_seconds=600.0)
        with pytest.raises(ClipPlanningError):
            planner.plan_clips(metadata, clip_duration_seconds=float("nan"), number_of_clips=1)

    def test_reject_inf_clip_duration(self, planner: ClipPlannerService):
        metadata = make_metadata(duration_seconds=600.0)
        with pytest.raises(ClipPlanningError):
            planner.plan_clips(metadata, clip_duration_seconds=float("inf"), number_of_clips=1)

    def test_reject_nan_or_inf_clip_count(self, planner: ClipPlannerService):
        metadata = make_metadata(duration_seconds=600.0)
        with pytest.raises(ClipPlanningError):
            planner.plan_clips(metadata, clip_duration_seconds=60.0, number_of_clips=float("nan"))  # type: ignore
        with pytest.raises(ClipPlanningError):
            planner.plan_clips(metadata, clip_duration_seconds=60.0, number_of_clips=float("inf"))  # type: ignore

    def test_reject_non_integer_float_clip_count(self, planner: ClipPlannerService):
        metadata = make_metadata(duration_seconds=600.0)
        with pytest.raises(ClipPlanningError):
            planner.plan_clips(metadata, clip_duration_seconds=60.0, number_of_clips=2.5)  # type: ignore

    def test_reject_boolean_parameters(self, planner: ClipPlannerService):
        metadata = make_metadata(duration_seconds=600.0)
        with pytest.raises(ClipPlanningError):
            planner.plan_clips(metadata, clip_duration_seconds=True, number_of_clips=2)  # type: ignore
        with pytest.raises(ClipPlanningError):
            planner.plan_clips(metadata, clip_duration_seconds=60.0, number_of_clips=True)  # type: ignore

    def test_reject_invalid_metadata_type(self, planner: ClipPlannerService):
        with pytest.raises(ClipPlanningError):
            planner.plan_clips(None, clip_duration_seconds=60.0, number_of_clips=1)  # type: ignore
        with pytest.raises(ClipPlanningError):
            planner.plan_clips("invalid_metadata", clip_duration_seconds=60.0, number_of_clips=1)  # type: ignore
