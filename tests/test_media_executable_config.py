from pathlib import Path

import pytest

from app.services.media_executable_config import (
    MediaExecutableConfigurationError,
    resolve_ffmpeg_executable,
    resolve_ffprobe_executable,
)


def test_default_ffmpeg_fallback(monkeypatch):
    monkeypatch.delenv("FFMPEG_PATH", raising=False)
    monkeypatch.setattr("app.services.media_executable_config.shutil.which", lambda name: None)

    assert resolve_ffmpeg_executable() == "ffmpeg"


def test_default_ffprobe_fallback(monkeypatch):
    monkeypatch.delenv("FFPROBE_PATH", raising=False)
    monkeypatch.setattr("app.services.media_executable_config.shutil.which", lambda name: None)

    assert resolve_ffprobe_executable() == "ffprobe"


def test_explicit_ffmpeg_path(monkeypatch, tmp_path: Path):
    executable = tmp_path / "ffmpeg.exe"
    executable.touch()
    monkeypatch.setenv("FFMPEG_PATH", str(executable))

    assert resolve_ffmpeg_executable() == str(executable)


def test_explicit_ffprobe_path(monkeypatch, tmp_path: Path):
    executable = tmp_path / "ffprobe.exe"
    executable.touch()
    monkeypatch.setenv("FFPROBE_PATH", str(executable))

    assert resolve_ffprobe_executable() == str(executable)


@pytest.mark.parametrize(
    ("environment_variable", "resolver", "display_name"),
    [
        ("FFMPEG_PATH", resolve_ffmpeg_executable, "FFmpeg"),
        ("FFPROBE_PATH", resolve_ffprobe_executable, "ffprobe"),
    ],
)
def test_invalid_configured_absolute_path(
    monkeypatch, tmp_path: Path, environment_variable, resolver, display_name
):
    missing = tmp_path / "missing.exe"
    monkeypatch.setenv(environment_variable, str(missing))

    with pytest.raises(
        MediaExecutableConfigurationError,
        match=f"Configured {display_name} executable was not found:",
    ):
        resolver()
