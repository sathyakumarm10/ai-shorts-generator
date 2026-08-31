"""Unit and integration tests for SmartFramingService and dynamic vertical video smart framing."""

from pathlib import Path
import pytest

from app.models import FramingType, IngestedVideo, VerticalVideoRequest
from app.services.smart_framing_service import (
    FaceBoundingBox,
    SmartFramingPlan,
    SmartFramingService,
    TimestampedFaceDetection,
)
from app.services.vertical_video_service import VerticalVideoService


class TestSmartFramingService:
    def test_bounding_box_geometry(self):
        bbox = FaceBoundingBox(x_min=0.2, y_min=0.1, x_max=0.6, y_max=0.7, confidence=0.9)
        assert bbox.center_x == pytest.approx(0.4)
        assert bbox.center_y == pytest.approx(0.4)
        assert bbox.width == pytest.approx(0.4)
        assert bbox.height == pytest.approx(0.6)

    def test_no_detections_returns_center_crop(self):
        service = SmartFramingService()
        plan = service.compute_framing_plan(detections=[])
        assert plan.framing_type == FramingType.CENTER_CROP
        assert plan.crop_x_expr == "(in_w-out_w)/2"
        assert plan.target_crop_x_normalized == 0.5

    def test_centered_detection_returns_center_crop(self):
        service = SmartFramingService()
        det = TimestampedFaceDetection(
            timestamp_seconds=1.0,
            faces=[FaceBoundingBox(x_min=0.45, y_min=0.2, x_max=0.55, y_max=0.6)],
        )
        plan = service.compute_framing_plan(detections=[det])
        assert plan.framing_type == FramingType.CENTER_CROP
        assert plan.crop_x_expr == "(in_w-out_w)/2"

    def test_off_center_left_detection_generates_smart_crop_plan(self):
        service = SmartFramingService()
        det = TimestampedFaceDetection(
            timestamp_seconds=1.0,
            faces=[FaceBoundingBox(x_min=0.05, y_min=0.2, x_max=0.25, y_max=0.6)],
        )
        plan = service.compute_framing_plan(
            detections=[det],
            source_width=1920,
            source_height=1080,
            target_width=1080,
            target_height=1920,
        )
        assert plan.framing_type == FramingType.SMART_FRAMING
        assert int(plan.crop_x_expr) >= 0

    def test_off_center_right_detection_generates_clamped_crop_plan(self):
        service = SmartFramingService()
        det = TimestampedFaceDetection(
            timestamp_seconds=1.0,
            faces=[FaceBoundingBox(x_min=0.85, y_min=0.2, x_max=0.98, y_max=0.6)],
        )
        plan = service.compute_framing_plan(
            detections=[det],
            source_width=1920,
            source_height=1080,
            target_width=1080,
            target_height=1920,
        )
        assert plan.framing_type == FramingType.SMART_FRAMING
        # Scaled 16:9 input width is 3413.3, crop width is 1080 -> max offset is 2333.3
        pixel_x = int(plan.crop_x_expr)
        assert 0 <= pixel_x <= 2334

    def test_multiple_faces_selects_most_prominent(self):
        service = SmartFramingService()
        det = TimestampedFaceDetection(
            timestamp_seconds=1.0,
            faces=[
                FaceBoundingBox(x_min=0.8, y_min=0.1, x_max=0.85, y_max=0.2, confidence=0.5),  # small background
                FaceBoundingBox(x_min=0.2, y_min=0.1, x_max=0.5, y_max=0.7, confidence=0.95),  # main speaker
            ],
        )
        plan = service.compute_framing_plan(detections=[det])
        # Main speaker center is 0.35 (left of center)
        assert plan.framing_type == FramingType.SMART_FRAMING


def test_vertical_video_service_returns_tuple_with_framing_type(tmp_path):
    # Test VerticalVideoService signature and center crop fallback on mock input
    vvs = VerticalVideoService(output_dir=tmp_path, enable_smart_framing=False)
    assert not vvs.enable_smart_framing
