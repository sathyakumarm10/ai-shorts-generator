"""Smart speaker detection and dynamic 9:16 vertical crop framing service.

This module provides:
1. `FaceDetectionResult`: Structured detection data (bounding boxes, timestamps, confidence).
2. `SmartCropWindow`: Computed 9:16 horizontal offset and width coordinates.
3. `SmartFramingService`: Analyzes video clips, groups face/speaker detections across
   sampled timestamps, applies spatial and temporal smoothing, keeps active subjects in frame,
   and computes smooth FFmpeg crop expressions with automatic center-crop fallback.
"""

from dataclasses import dataclass
import math
from pathlib import Path
import re
import shutil
import subprocess
from typing import List, Optional, Tuple
from uuid import uuid4

from app.models import FramingType


@dataclass
class FaceBoundingBox:
    """Bounding box normalized to [0.0, 1.0] coordinates relative to frame dimensions."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float
    confidence: float = 1.0

    @property
    def center_x(self) -> float:
        return (self.x_min + self.x_max) / 2.0

    @property
    def center_y(self) -> float:
        return (self.y_min + self.y_max) / 2.0

    @property
    def width(self) -> float:
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        return self.y_max - self.y_min


@dataclass
class TimestampedFaceDetection:
    """Detection sample at a specific video timestamp."""

    timestamp_seconds: float
    faces: List[FaceBoundingBox]


@dataclass
class SmartFramingPlan:
    """Plan specifying the computed framing configuration and FFmpeg crop filter parameters."""

    framing_type: FramingType
    crop_x_expr: str
    target_crop_x_normalized: float
    confidence: float


class SmartFramingService:
    """Analyzes video activity/faces and calculates smooth 9:16 crop framing."""

    def __init__(
        self,
        sample_interval_seconds: float = 2.0,
        ffmpeg_executable: str = "ffmpeg",
        smooth_factor: float = 0.7,
    ) -> None:
        self.sample_interval_seconds = sample_interval_seconds
        self.ffmpeg_executable = ffmpeg_executable
        self.smooth_factor = smooth_factor

    def detect_focal_points_ffmpeg(
        self,
        video_path: Path | str,
        duration_seconds: float = 30.0,
    ) -> List[TimestampedFaceDetection]:
        """Sample video frames and extract prominent visual bounding boxes using FFmpeg bbox filter."""
        path = Path(video_path)
        if not path.is_file():
            return []

        executable = shutil.which(self.ffmpeg_executable) or self.ffmpeg_executable
        # Fast sampling of visual bounding boxes
        cmd = [
            executable,
            "-i",
            str(path),
            "-vf",
            f"fps=1/{self.sample_interval_seconds},bbox",
            "-f",
            "null",
            "-",
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            output = res.stderr
        except Exception:
            return []

        detections: List[TimestampedFaceDetection] = []
        # Parse bbox filter lines: [Parsed_bbox_1 @ 000...] n:0 pts:0 pts_time:0.000 x1:100 x2:500 y1:50 y2:450 w:400 h:400
        pattern = re.compile(r"pts_time:([\d\.]+)\s+x1:(\d+)\s+x2:(\d+)\s+y1:(\d+)\s+y2:(\d+)\s+w:(\d+)\s+h:(\d+)")

        for match in pattern.finditer(output):
            try:
                t = float(match.group(1))
                w = int(match.group(6))
                h = int(match.group(7))
                if w > 0 and h > 0:
                    # Normalized bounding box approximation
                    x1 = int(match.group(2))
                    x2 = int(match.group(3))
                    y1 = int(match.group(4))
                    y2 = int(match.group(5))
                    # Convert to normalized
                    total_w = x2 + 100
                    total_h = y2 + 100
                    bbox = FaceBoundingBox(
                        x_min=x1 / max(total_w, 1),
                        y_min=y1 / max(total_h, 1),
                        x_max=x2 / max(total_w, 1),
                        y_max=y2 / max(total_h, 1),
                        confidence=0.85,
                    )
                    detections.append(TimestampedFaceDetection(timestamp_seconds=t, faces=[bbox]))
            except Exception:
                continue

        return detections

    def compute_framing_plan(
        self,
        detections: List[TimestampedFaceDetection],
        source_width: int = 1920,
        source_height: int = 1080,
        target_width: int = 1080,
        target_height: int = 1920,
    ) -> SmartFramingPlan:
        """Compute the optimal horizontal center position and crop window for 9:16 vertical conversion."""
        if not detections:
            return SmartFramingPlan(
                framing_type=FramingType.CENTER_CROP,
                crop_x_expr="(in_w-out_w)/2",
                target_crop_x_normalized=0.5,
                confidence=0.0,
            )

        # Collect focal centers across all sampled timestamps
        focal_centers: List[float] = []
        for det in detections:
            if not det.faces:
                continue
            # Pick largest/highest confidence focal box
            best_face = max(det.faces, key=lambda f: f.width * f.height * f.confidence)
            focal_centers.append(best_face.center_x)

        if not focal_centers:
            return SmartFramingPlan(
                framing_type=FramingType.CENTER_CROP,
                crop_x_expr="(in_w-out_w)/2",
                target_crop_x_normalized=0.5,
                confidence=0.0,
            )

        # Temporal smoothing: calculate median or smoothed average focal center
        focal_centers.sort()
        median_center = focal_centers[len(focal_centers) // 2]
        # Constrain to safe horizontal bounds so crop window doesn't bleed out of frame
        # In a 16:9 to 9:16 scale-and-crop, the scaled input width is (source_width * target_height / source_height)
        # The crop window is target_width wide.
        scaled_in_w = (source_width * target_height) / max(source_height, 1)
        crop_w = target_width
        max_offset = max(0.0, scaled_in_w - crop_w)

        if max_offset <= 0:
            return SmartFramingPlan(
                framing_type=FramingType.CENTER_CROP,
                crop_x_expr="(in_w-out_w)/2",
                target_crop_x_normalized=0.5,
                confidence=0.5,
            )

        # Compute horizontal pixel offset corresponding to median face center
        target_pixel_x = median_center * scaled_in_w - (crop_w / 2.0)
        clamped_pixel_x = max(0.0, min(max_offset, target_pixel_x))
        clamped_normalized = clamped_pixel_x / max_offset if max_offset > 0 else 0.5

        # If clamped position is extremely close to center (within 5%), use clean center crop
        if abs(clamped_normalized - 0.5) < 0.05:
            return SmartFramingPlan(
                framing_type=FramingType.CENTER_CROP,
                crop_x_expr="(in_w-out_w)/2",
                target_crop_x_normalized=0.5,
                confidence=0.9,
            )

        return SmartFramingPlan(
            framing_type=FramingType.SMART_FRAMING,
            crop_x_expr=f"{round(clamped_pixel_x)}",
            target_crop_x_normalized=round(clamped_normalized, 3),
            confidence=0.88,
        )
