"""Vertical 9:16 video conversion service using FFmpeg.

This module provides the `VerticalVideoService` for converting landscape video
clips into standard 9:16 vertical Shorts format using scaling and center-cropping
without distorting or stretching the original aspect ratio.
"""

from pathlib import Path
import shutil
import subprocess
from typing import Optional, Tuple
from uuid import uuid4

from app.models import FramingType, IngestedVideo, VerticalVideoRequest
from app.services.acceleration_service import HardwareAccelerationService, default_acceleration_service
from app.services.smart_framing_service import SmartFramingPlan, SmartFramingService

# Default directory for generated vertical clips, located in the ignored `outputs/vertical` area.
DEFAULT_VERTICAL_OUTPUT_DIR = Path("outputs") / "vertical"


class VerticalVideoError(Exception):
    """Domain exception raised when vertical video conversion fails."""

    pass


class VerticalVideoService:
    """Service responsible for converting video clips into framed 9:16 vertical MP4 format."""

    def __init__(
        self,
        output_dir: Path | str = DEFAULT_VERTICAL_OUTPUT_DIR,
        ffmpeg_executable: str = "ffmpeg",
        smart_framing_service: Optional[SmartFramingService] = None,
        enable_smart_framing: bool = True,
        acceleration_service: Optional[HardwareAccelerationService] = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.ffmpeg_executable = ffmpeg_executable
        self.smart_framing_service = smart_framing_service or SmartFramingService(
            ffmpeg_executable=self.ffmpeg_executable
        )
        self.enable_smart_framing = enable_smart_framing
        self.acceleration_service = acceleration_service or default_acceleration_service

    def convert_to_vertical(
        self,
        video: IngestedVideo | str | Path,
        request: Optional[VerticalVideoRequest] = None,
        use_smart_framing: Optional[bool] = None,
        output_filename: Optional[str] = None,
    ) -> IngestedVideo:
        """Convert a video file into a 9:16 vertical MP4 video using scale and smart or center-crop.

        Args:
            video: An IngestedVideo model or local file path to the source video.
            request: Optional VerticalVideoRequest specifying target width and height (defaults to 1080x1920).
            use_smart_framing: Optional flag overriding whether to attempt dynamic smart speaker framing.
            output_filename: Optional custom output filename.

        Returns:
            IngestedVideo: Contains file_path and framing_type for the vertical MP4 video.

        Raises:
            VerticalVideoError: If source video is missing/empty, request is invalid,
                                FFmpeg execution fails, or the output file is not generated.
        """
        # Resolve source video file path
        if isinstance(video, IngestedVideo):
            source_path = Path(video.file_path)
        elif isinstance(video, (str, Path)):
            source_path = Path(video)
        else:
            raise VerticalVideoError(
                f"Invalid video type: expected IngestedVideo, str, or Path, got {type(video).__name__}"
            )

        if not source_path.is_file():
            raise VerticalVideoError(f"Source video file not found: {source_path}")

        try:
            source_size = source_path.stat().st_size
            if source_size <= 0:
                raise VerticalVideoError(f"Source video file is empty (0 bytes): {source_path}")
        except OSError as exc:
            raise VerticalVideoError(f"Could not read source video file: {exc}") from exc

        # Use default 1080x1920 vertical request if none provided
        req = request or VerticalVideoRequest()
        if not isinstance(req, VerticalVideoRequest):
            raise VerticalVideoError(
                f"Invalid request type: expected VerticalVideoRequest, got {type(req).__name__}"
            )

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Generate output filename inside output_dir
        if output_filename:
            output_path = self.output_dir / output_filename
        else:
            unique_id = uuid4().hex
            output_path = self.output_dir / f"vertical_{unique_id}.mp4"

        # Check for FFmpeg executable
        executable = shutil.which(self.ffmpeg_executable) or self.ffmpeg_executable

        # Determine framing plan (Smart framing vs center crop)
        should_smart_frame = self.enable_smart_framing if use_smart_framing is None else use_smart_framing
        framing_plan = SmartFramingPlan(
            framing_type=FramingType.CENTER_CROP,
            crop_x_expr="(in_w-out_w)/2",
            target_crop_x_normalized=0.5,
            confidence=0.0,
        )

        if should_smart_frame:
            try:
                detections = self.smart_framing_service.detect_focal_points_ffmpeg(source_path)
                framing_plan = self.smart_framing_service.compute_framing_plan(
                    detections=detections,
                    target_width=req.width,
                    target_height=req.height,
                )
            except Exception:
                # Safe fallback to center crop
                framing_plan = SmartFramingPlan(
                    framing_type=FramingType.CENTER_CROP,
                    crop_x_expr="(in_w-out_w)/2",
                    target_crop_x_normalized=0.5,
                    confidence=0.0,
                )

        # Build FFmpeg filter expression with smart or center crop
        crop_x = framing_plan.crop_x_expr
        filter_expr = f"scale={req.width}:{req.height}:force_original_aspect_ratio=increase,crop={req.width}:{req.height}:{crop_x}:(in_h-out_h)/2"

        def build_cmd(use_nvenc: bool) -> list[str]:
            v_flags = ["-c:v", "h264_nvenc", "-preset", "p4"] if use_nvenc else ["-c:v", "libx264"]
            return [
                executable,
                "-y",  # Overwrite output file if exists
                "-i",
                str(source_path),
                "-vf",
                filter_expr,
                *v_flags,
                "-c:a",
                "aac",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output_path),
            ]

        def validator() -> bool:
            return output_path.is_file() and output_path.stat().st_size > 0

        try:
            result = self.acceleration_service.run_ffmpeg_with_fallback(
                command_builder=build_cmd,
                output_file_validator=validator,
                ffmpeg_executable=self.ffmpeg_executable,
            )
        except FileNotFoundError as exc:
            raise VerticalVideoError(
                f"FFmpeg executable '{self.ffmpeg_executable}' not found on system path."
            ) from exc
        except Exception as exc:
            raise VerticalVideoError(f"Failed to execute FFmpeg for vertical conversion: {exc}") from exc

        if result.returncode != 0:
            err_msg = result.stderr.strip() or "Unknown FFmpeg error"
            raise VerticalVideoError(f"FFmpeg vertical conversion failed: {err_msg}")

        if not output_path.is_file():
            raise VerticalVideoError(
                f"FFmpeg reported success, but generated vertical video was not found at: {output_path}"
            )

        try:
            output_size = output_path.stat().st_size
            if output_size <= 0:
                raise VerticalVideoError(
                    f"Generated vertical video file is empty (0 bytes): {output_path}"
                )
        except OSError as exc:
            raise VerticalVideoError(f"Could not verify generated vertical video file: {exc}") from exc

        return IngestedVideo(
            file_path=str(output_path),
            framing_type=framing_plan.framing_type,
        )
