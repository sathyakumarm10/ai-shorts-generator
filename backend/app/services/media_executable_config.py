"""Resolve configured FFmpeg and ffprobe executables."""

import os
from pathlib import Path
import shutil
from typing import Optional


class MediaExecutableConfigurationError(RuntimeError):
    """Raised when an explicitly configured media executable is invalid."""


def _resolve_executable(
    *,
    override: Optional[str],
    environment_variable: str,
    fallback: str,
    display_name: str,
) -> str:
    configured_value = os.environ.get(environment_variable, "").strip()
    executable = override if override is not None else configured_value or fallback
    executable = str(executable).strip()

    executable_path = Path(executable)
    if executable_path.is_absolute():
        if not executable_path.is_file():
            raise MediaExecutableConfigurationError(
                f"Configured {display_name} executable was not found: {executable}"
            )
        return str(executable_path)

    return shutil.which(executable) or executable


def resolve_ffmpeg_executable(override: Optional[str] = None) -> str:
    """Resolve FFmpeg from an override, FFMPEG_PATH, or the system PATH."""
    return _resolve_executable(
        override=override,
        environment_variable="FFMPEG_PATH",
        fallback="ffmpeg",
        display_name="FFmpeg",
    )


def resolve_ffprobe_executable(override: Optional[str] = None) -> str:
    """Resolve ffprobe from an override, FFPROBE_PATH, or the system PATH."""
    return _resolve_executable(
        override=override,
        environment_variable="FFPROBE_PATH",
        fallback="ffprobe",
        display_name="ffprobe",
    )
