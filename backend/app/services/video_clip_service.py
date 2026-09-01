"""Video clip generation service using FFmpeg.

This module provides the `VideoClipService` for cutting requested time segments
from an already-ingested video file and saving them as new MP4 clips.
"""

from pathlib import Path
import shutil
import subprocess
from typing import Optional
from uuid import uuid4

from app.models import IngestedVideo, VideoClipRequest, VideoMetadata
from app.services.acceleration_service import HardwareAccelerationService, default_acceleration_service

# Default directory for generated clips, located in the ignored `outputs/clips` area.
DEFAULT_OUTPUT_DIR = Path("outputs") / "clips"


class VideoClipError(Exception):
    """Domain exception raised when video clip extraction or generation fails."""

    pass


class VideoClipService:
    """Service responsible for cutting video segments into standalone MP4 clips."""

    def __init__(
        self,
        output_dir: Path | str = DEFAULT_OUTPUT_DIR,
        ffmpeg_executable: str = "ffmpeg",
        acceleration_service: Optional[HardwareAccelerationService] = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.ffmpeg_executable = ffmpeg_executable
        self.acceleration_service = acceleration_service or default_acceleration_service

    def create_clip(
        self,
        video: IngestedVideo | str | Path,
        clip_request: VideoClipRequest,
        metadata: Optional[VideoMetadata] = None,
    ) -> IngestedVideo:
        """Cut a time segment from an ingested video using FFmpeg.

        Args:
            video: An IngestedVideo model or local file path to the source video.
            clip_request: VideoClipRequest specifying start_seconds and duration_seconds.
            metadata: Optional VideoMetadata for source duration validation.

        Returns:
            IngestedVideo: Contains the local file path to the newly generated MP4 clip.

        Raises:
            VideoClipError: If source video is missing, start_seconds is out of bounds,
                           FFmpeg fails, or the output file is not generated.
        """
        # Resolve source video file path
        if isinstance(video, IngestedVideo):
            input_path = Path(video.file_path)
        else:
            input_path = Path(video)

        if not input_path.is_file():
            raise VideoClipError(f"Source video file not found: {input_path}")

        # Validate start timestamp against source metadata if provided
        if metadata is not None:
            if clip_request.start_seconds >= metadata.duration_seconds:
                raise VideoClipError(
                    f"Clip start timestamp ({clip_request.start_seconds}s) is at or beyond "
                    f"source video duration ({metadata.duration_seconds}s)."
                )

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Generate unique, collision-resistant output filename inside output_dir
        unique_clip_id = uuid4().hex
        output_path = self.output_dir / f"clip_{unique_clip_id}.mp4"

        # Check for executable
        executable = shutil.which(self.ffmpeg_executable) or self.ffmpeg_executable

        # Build FFmpeg command with safe list of arguments (shell=False)
        def build_cmd(use_nvenc: bool) -> list[str]:
            v_flags = ["-c:v", "h264_nvenc", "-preset", "p4"] if use_nvenc else ["-c:v", "libx264"]
            return [
                executable,
                "-y",  # Overwrite output file if exists
                "-ss",
                str(clip_request.start_seconds),
                "-i",
                str(input_path),
                "-t",
                str(clip_request.duration_seconds),
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
            raise VideoClipError(
                f"FFmpeg executable '{self.ffmpeg_executable}' not found on system path."
            ) from exc
        except Exception as exc:
            raise VideoClipError(f"Failed to execute FFmpeg: {exc}") from exc

        if result.returncode != 0:
            err_msg = result.stderr.strip() or "Unknown FFmpeg error"
            raise VideoClipError(f"FFmpeg clip generation failed: {err_msg}")

        if not output_path.is_file():
            raise VideoClipError(
                f"FFmpeg reported success, but generated clip was not found at: {output_path}"
            )

        return IngestedVideo(file_path=str(output_path))
