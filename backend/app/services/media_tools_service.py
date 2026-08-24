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


@dataclass(frozen=True)
class ToolStatus:
    """Represents the availability status and path of an external executable tool."""

    available: bool
    path: Optional[str] = None


@dataclass(frozen=True)
class MediaToolsReport:
    """Structured report containing status for ffmpeg, ffprobe, and yt-dlp."""

    ffmpeg: ToolStatus
    ffprobe: ToolStatus
    yt_dlp: ToolStatus


class MediaToolsService:
    """Service responsible for discovering and checking availability of external media tools."""

    FFMPEG_CMD = "ffmpeg"
    FFPROBE_CMD = "ffprobe"
    YT_DLP_CMD = "yt-dlp"

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
        """Check availability for all required media processing tools.

        Returns:
            MediaToolsReport: Structured availability for ffmpeg, ffprobe, and yt-dlp.
        """
        return MediaToolsReport(
            ffmpeg=self.check_tool(self.FFMPEG_CMD),
            ffprobe=self.check_tool(self.FFPROBE_CMD),
            yt_dlp=self.check_tool(self.YT_DLP_CMD),
        )
