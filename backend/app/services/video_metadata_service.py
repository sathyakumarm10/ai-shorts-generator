"""Video metadata extraction service.

This module provides the `VideoMetadataService` for inspecting ingested video
files using `ffprobe` to extract duration, dimensions, container format, and
file size.
"""

import json
from pathlib import Path
import shutil
import subprocess

from app.models import IngestedVideo, VideoMetadata


class VideoMetadataError(Exception):
    """Domain exception raised when video metadata extraction fails."""

    pass


class VideoMetadataService:
    """Service responsible for extracting technical metadata from an ingested video."""

    def __init__(self, ffprobe_executable: str = "ffprobe") -> None:
        self.ffprobe_executable = ffprobe_executable

    def extract_metadata(self, video: IngestedVideo | str | Path) -> VideoMetadata:
        """Extract metadata from an IngestedVideo or video file path using ffprobe.

        Args:
            video: An IngestedVideo model or Path/string pointing to the local video file.

        Returns:
            VideoMetadata: Extracted video duration, resolution, format, and file size.

        Raises:
            VideoMetadataError: If the file does not exist, ffprobe is not found,
                               execution fails, or metadata is malformed/incomplete.
        """
        # Resolve the local file path
        if isinstance(video, IngestedVideo):
            file_path = Path(video.file_path)
        else:
            file_path = Path(video)

        if not file_path.is_file():
            raise VideoMetadataError(f"Video file not found: {file_path}")

        # Compute file size directly from disk to ensure authenticity
        try:
            file_size_bytes = file_path.stat().st_size
        except OSError as exc:
            raise VideoMetadataError(f"Could not read video file size: {exc}") from exc

        # Check for ffprobe availability
        executable = shutil.which(self.ffprobe_executable) or self.ffprobe_executable

        cmd = [
            executable,
            "-v",
            "error",
            "-show_entries",
            "stream=width,height:format=duration,format_name",
            "-select_streams",
            "v:0",
            "-of",
            "json",
            str(file_path),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise VideoMetadataError(
                f"ffprobe executable '{self.ffprobe_executable}' not found on system path."
            ) from exc
        except Exception as exc:
            raise VideoMetadataError(f"Failed to execute ffprobe: {exc}") from exc

        if result.returncode != 0:
            error_detail = result.stderr.strip() or "Unknown error"
            raise VideoMetadataError(f"ffprobe inspection failed: {error_detail}")

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise VideoMetadataError("Failed to parse ffprobe JSON output.") from exc

        format_info = data.get("format", {})
        streams = data.get("streams", [])

        # Duration parsing
        duration_raw = format_info.get("duration")
        if duration_raw is None:
            raise VideoMetadataError("ffprobe output does not contain duration information.")
        try:
            duration_seconds = float(duration_raw)
            if duration_seconds <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise VideoMetadataError(f"Invalid duration value returned by ffprobe: {duration_raw}")

        # Container format name
        format_name = format_info.get("format_name")
        if not format_name:
            raise VideoMetadataError("ffprobe output does not contain format name.")

        # Video stream dimensions (width, height)
        if not streams:
            raise VideoMetadataError("No video streams found in the media file.")

        video_stream = streams[0]
        width = video_stream.get("width")
        height = video_stream.get("height")

        if width is None or height is None:
            raise VideoMetadataError("Video stream dimensions (width/height) are missing.")

        try:
            width = int(width)
            height = int(height)
            if width <= 0 or height <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise VideoMetadataError(f"Invalid video dimensions: width={width}, height={height}")

        return VideoMetadata(
            duration_seconds=duration_seconds,
            width=width,
            height=height,
            format=format_name,
            file_size_bytes=file_size_bytes,
        )
