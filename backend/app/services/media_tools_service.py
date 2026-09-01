"""Media tools capability and availability health service.

This module provides the `MediaToolsService` to check whether required external
command-line executables (`ffmpeg`, `ffprobe`, and `yt-dlp`) are installed and
discoverable on the system PATH or virtual environment.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sys
from typing import Optional

from app.services.acceleration_service import (
    AccelerationReport,
    HardwareAccelerationService,
    default_acceleration_service,
)


@dataclass(frozen=True)
class ToolStatus:
    """Represents the availability status and path of an external executable tool."""

    available: bool
    path: Optional[str] = None


@dataclass(frozen=True)
class MediaToolsReport:
    """Structured report containing status for ffmpeg, ffprobe, yt-dlp, and hardware acceleration."""

    ffmpeg: ToolStatus
    ffprobe: ToolStatus
    yt_dlp: ToolStatus
    acceleration: Optional[AccelerationReport] = None


class MediaToolsService:
    """Service responsible for discovering and checking availability of external media tools."""

    FFMPEG_CMD = "ffmpeg"
    FFPROBE_CMD = "ffprobe"
    YT_DLP_CMD = "yt-dlp"

    def __init__(self, acceleration_service: Optional[HardwareAccelerationService] = None) -> None:
        self.acceleration_service = acceleration_service or default_acceleration_service

    def check_tool(self, tool_name: str) -> ToolStatus:
        """Check if an executable is discoverable via system PATH or Python scripts directory.

        Args:
            tool_name: The name of the executable to discover.

        Returns:
            ToolStatus: available boolean and resolved path if found.
        """
        # Search system PATH first
        resolved = shutil.which(tool_name)

        # Also search current Python environment scripts directory if not on global PATH
        if not resolved and sys.executable:
            venv_bin_dir = os.path.dirname(sys.executable)
            resolved = shutil.which(tool_name, path=venv_bin_dir)

        if resolved:
            return ToolStatus(available=True, path=str(Path(resolved).resolve()))
        return ToolStatus(available=False, path=None)

    def check_all(self) -> MediaToolsReport:
        """Check availability for all required media processing tools and acceleration status.

        Returns:
            MediaToolsReport: Structured availability for ffmpeg, ffprobe, yt-dlp, and acceleration.
        """
        ffmpeg_status = self.check_tool(self.FFMPEG_CMD)
        ffmpeg_bin = ffmpeg_status.path or self.FFMPEG_CMD
        return MediaToolsReport(
            ffmpeg=ffmpeg_status,
            ffprobe=self.check_tool(self.FFPROBE_CMD),
            yt_dlp=self.check_tool(self.YT_DLP_CMD),
            acceleration=self.acceleration_service.get_acceleration_report(ffmpeg_executable=ffmpeg_bin),
        )
