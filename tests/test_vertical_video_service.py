"""Unit tests for VerticalVideoService.

These tests verify model validations, FFmpeg command formulation, argument parameters,
error handling, and file verification without running real FFmpeg rendering.
"""

from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch
import pytest
from pydantic import ValidationError

from app.models import IngestedVideo, VerticalVideoRequest
from app.services.vertical_video_service import VerticalVideoError, VerticalVideoService


# ---------------------------------------------------------------------------
# VerticalVideoRequest Model Tests
# ---------------------------------------------------------------------------


class TestVerticalVideoRequestModel:
    def test_default_resolution_is_1080x1920(self):
        req = VerticalVideoRequest()
        assert req.width == 1080
        assert req.height == 1920

    def test_valid_custom_9_16_dimensions(self):
        req = VerticalVideoRequest(width=720, height=1280)
        assert req.width == 720
        assert req.height == 1280

    def test_reject_zero_or_negative_dimensions(self):
        with pytest.raises(ValidationError):
            VerticalVideoRequest(width=0, height=1920)
        with pytest.raises(ValidationError):
            VerticalVideoRequest(width=1080, height=0)
        with pytest.raises(ValidationError):
            VerticalVideoRequest(width=-1080, height=1920)
        with pytest.raises(ValidationError):
            VerticalVideoRequest(width=1080, height=-1920)

    def test_reject_invalid_aspect_ratios(self):
        # 16:9 landscape aspect ratio
        with pytest.raises(ValidationError):
            VerticalVideoRequest(width=1920, height=1080)
        # 1:1 square aspect ratio
        with pytest.raises(ValidationError):
            VerticalVideoRequest(width=1000, height=1000)

    def test_reject_boolean_dimensions(self):
        with pytest.raises(ValidationError):
            VerticalVideoRequest(width=True, height=1920)  # type: ignore
        with pytest.raises(ValidationError):
            VerticalVideoRequest(width=1080, height=True)  # type: ignore


# ---------------------------------------------------------------------------
# VerticalVideoService Unit Tests (Mocked Subprocess)
# ---------------------------------------------------------------------------


class TestVerticalVideoServiceUnit:
    def test_reject_missing_source_file(self, tmp_path: Path):
        service = VerticalVideoService(output_dir=tmp_path / "vertical_out")
        missing_file = tmp_path / "non_existent.mp4"

        with pytest.raises(VerticalVideoError) as exc_info:
            service.convert_to_vertical(missing_file)
        assert "not found" in str(exc_info.value).lower()

    def test_reject_empty_source_file(self, tmp_path: Path):
        service = VerticalVideoService(output_dir=tmp_path / "vertical_out")
        empty_file = tmp_path / "empty.mp4"
        empty_file.write_bytes(b"")

        with pytest.raises(VerticalVideoError) as exc_info:
            service.convert_to_vertical(empty_file)
        assert "empty" in str(exc_info.value).lower()

    @patch("subprocess.run")
    def test_ffmpeg_command_structure_and_arguments(self, mock_run: MagicMock, tmp_path: Path):
        out_dir = tmp_path / "vertical_out"
        service = VerticalVideoService(output_dir=out_dir)

        source_file = tmp_path / "source.mp4"
        source_file.write_bytes(b"mock_video_bytes_123")

        # Simulate successful conversion
        def side_effect(cmd, **kwargs):
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"mock_vertical_mp4_bytes")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect

        result = service.convert_to_vertical(source_file)

        assert mock_run.called
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        kwargs = call_args[1]

        # 1. Verify list arguments and shell=False
        assert isinstance(cmd, list)
        assert kwargs.get("check") is False
        assert "shell" not in kwargs or kwargs["shell"] is False

        # 2. Verify filters and codecs
        assert "-vf" in cmd
        vf_idx = cmd.index("-vf")
        filter_str = cmd[vf_idx + 1]
        assert "scale=1080:1920:force_original_aspect_ratio=increase" in filter_str
        assert "crop=1080:1920" in filter_str

        assert "-c:v" in cmd
        assert cmd[cmd.index("-c:v") + 1] == "libx264"

        assert "-c:a" in cmd
        assert cmd[cmd.index("-c:a") + 1] == "aac"

        assert "-pix_fmt" in cmd
        assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"

        assert "-movflags" in cmd
        assert cmd[cmd.index("-movflags") + 1] == "+faststart"

        assert isinstance(result, IngestedVideo)
        assert Path(result.file_path).is_file()

    @patch("subprocess.run")
    def test_ffmpeg_failure_raises_vertical_video_error(self, mock_run: MagicMock, tmp_path: Path):
        service = VerticalVideoService(output_dir=tmp_path / "vertical_out")
        source_file = tmp_path / "source.mp4"
        source_file.write_bytes(b"mock_video_bytes_123")

        mock_run.return_value = subprocess.CompletedProcess(
            args=["ffmpeg"], returncode=1, stdout="", stderr="Error decoding stream"
        )

        with pytest.raises(VerticalVideoError) as exc_info:
            service.convert_to_vertical(source_file)
        assert "Error decoding stream" in str(exc_info.value) or "failed" in str(exc_info.value).lower()

    @patch("subprocess.run")
    def test_missing_output_file_raises_vertical_video_error(self, mock_run: MagicMock, tmp_path: Path):
        service = VerticalVideoService(output_dir=tmp_path / "vertical_out")
        source_file = tmp_path / "source.mp4"
        source_file.write_bytes(b"mock_video_bytes_123")

        # Subprocess returns 0, but output file is never created
        mock_run.return_value = subprocess.CompletedProcess(
            args=["ffmpeg"], returncode=0, stdout="", stderr=""
        )

        with pytest.raises(VerticalVideoError) as exc_info:
            service.convert_to_vertical(source_file)
        assert "not found" in str(exc_info.value).lower()

    @patch("subprocess.run")
    def test_empty_output_file_raises_vertical_video_error(self, mock_run: MagicMock, tmp_path: Path):
        service = VerticalVideoService(output_dir=tmp_path / "vertical_out")
        source_file = tmp_path / "source.mp4"
        source_file.write_bytes(b"mock_video_bytes_123")

        def side_effect(cmd, **kwargs):
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"")  # 0 bytes
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect

        with pytest.raises(VerticalVideoError) as exc_info:
            service.convert_to_vertical(source_file)
        assert "empty" in str(exc_info.value).lower()
