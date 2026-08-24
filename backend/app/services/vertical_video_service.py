"""Vertical 9:16 video conversion service using FFmpeg.

This module provides the `VerticalVideoService` for converting landscape video
clips into standard 9:16 vertical Shorts format using scaling and center-cropping
without distorting or stretching the original aspect ratio.
"""

from pathlib import Path
import shutil
import subprocess
from typing import Optional
from uuid import uuid4

from app.models import IngestedVideo, VerticalVideoRequest

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
    ) -> None:
        self.output_dir = Path(output_dir)
        self.ffmpeg_executable = ffmpeg_executable

    def convert_to_vertical(
        self,
        video: IngestedVideo | str | Path,
        request: Optional[VerticalVideoRequest] = None,
    ) -> IngestedVideo:
        """Convert a video file into a 9:16 vertical MP4 video using scale and center-crop.

        Args:
            video: An IngestedVideo model or local file path to the source video.
            request: Optional VerticalVideoRequest specifying target width and height (defaults to 1080x1920).

        Returns:
            IngestedVideo: Contains the local file path to the newly generated vertical MP4 video.

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

        # Generate unique, collision-resistant output filename inside output_dir
        unique_id = uuid4().hex
        output_path = self.output_dir / f"vertical_{unique_id}.mp4"

        # Check for FFmpeg executable
        executable = shutil.which(self.ffmpeg_executable) or self.ffmpeg_executable

        # Build FFmpeg command with safe list of arguments (shell=False)
        # Using scale-before-crop to cover the 9:16 frame then center-crop the excess area
        filter_expr = f"scale={req.width}:{req.height}:force_original_aspect_ratio=increase,crop={req.width}:{req.height}"

        cmd = [
            executable,
            "-y",  # Overwrite output file if exists (unique name prevents collisions)
            "-i",
            str(source_path),
            "-vf",
            filter_expr,
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
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

        return IngestedVideo(file_path=str(output_path))
