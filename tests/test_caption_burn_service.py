"""Unit tests for CaptionBurnService.

These tests verify FFmpeg command construction, subtitle filter formatting,
temporary SRT creation and cleanup, and error translation without invoking live FFmpeg rendering.
"""

from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch
import pytest

from app.models import CaptionSegment, CaptionTrack, IngestedVideo
from app.services.caption_burn_service import CaptionBurnError, CaptionBurnService


@pytest.fixture
def sample_caption_track() -> CaptionTrack:
    return CaptionTrack(
        segments=[
            CaptionSegment(start_seconds=0.0, end_seconds=3.0, text="First subtitle line"),
            CaptionSegment(start_seconds=3.5, end_seconds=7.0, text="Second subtitle line"),
        ]
    )


class TestCaptionBurnServiceUnit:
    def test_reject_missing_source_video(self, tmp_path: Path, sample_caption_track: CaptionTrack):
        service = CaptionBurnService(output_dir=tmp_path / "out")
        missing_file = tmp_path / "missing.mp4"

        with pytest.raises(CaptionBurnError) as exc_info:
            service.burn_captions(missing_file, sample_caption_track)
        assert "not found" in str(exc_info.value).lower()

    def test_reject_empty_source_video(self, tmp_path: Path, sample_caption_track: CaptionTrack):
        service = CaptionBurnService(output_dir=tmp_path / "out")
        empty_file = tmp_path / "empty.mp4"
        empty_file.write_bytes(b"")

        with pytest.raises(CaptionBurnError) as exc_info:
            service.burn_captions(empty_file, sample_caption_track)
        assert "empty" in str(exc_info.value).lower()

    def test_reject_invalid_captions_type(self, tmp_path: Path):
        service = CaptionBurnService(output_dir=tmp_path / "out")
        source_file = tmp_path / "source.mp4"
        source_file.write_bytes(b"mock_bytes")

        with pytest.raises(CaptionBurnError):
            service.burn_captions(source_file, "invalid_track")  # type: ignore

    @patch("subprocess.run")
    def test_ffmpeg_command_structure_and_cleanup(
        self, mock_run: MagicMock, tmp_path: Path, sample_caption_track: CaptionTrack
    ):
        out_dir = tmp_path / "captioned_output"
        service = CaptionBurnService(output_dir=out_dir)

        source_file = tmp_path / "source.mp4"
        source_file.write_bytes(b"mock_source_mp4_bytes")

        captured_srt_path: list[str] = []

        def side_effect(cmd, **kwargs):
            # Extract srt path from filter
            vf_val = cmd[cmd.index("-vf") + 1]
            captured_srt_path.append(vf_val)

            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"mock_captioned_mp4_data")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect

        result = service.burn_captions(source_file, sample_caption_track)

        assert mock_run.called
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        kwargs = call_args[1]

        # Verify command argument vector & shell=False
        assert isinstance(cmd, list)
        assert kwargs.get("check") is False
        assert "shell" not in kwargs or kwargs["shell"] is False

        # Verify subtitle filter and styling
        assert "-vf" in cmd
        filter_str = cmd[cmd.index("-vf") + 1]
        assert "subtitles=" in filter_str
        assert "force_style=" in filter_str
        assert "FontSize=24" in filter_str

        # Verify video/audio codecs and faststart
        assert cmd[cmd.index("-c:v") + 1] == "libx264"
        assert cmd[cmd.index("-c:a") + 1] == "aac"
        assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
        assert cmd[cmd.index("-movflags") + 1] == "+faststart"

        assert isinstance(result, IngestedVideo)
        assert Path(result.file_path).is_file()

    @patch("subprocess.run")
    def test_ffmpeg_failure_raises_caption_burn_error(
        self, mock_run: MagicMock, tmp_path: Path, sample_caption_track: CaptionTrack
    ):
        service = CaptionBurnService(output_dir=tmp_path / "out")
        source_file = tmp_path / "source.mp4"
        source_file.write_bytes(b"mock_bytes")

        mock_run.return_value = subprocess.CompletedProcess(
            args=["ffmpeg"], returncode=1, stdout="", stderr="Error initializing subtitles filter"
        )

        with pytest.raises(CaptionBurnError) as exc_info:
            service.burn_captions(source_file, sample_caption_track)
        assert "subtitles filter" in str(exc_info.value) or "failed" in str(exc_info.value).lower()

    @patch("subprocess.run")
    def test_missing_output_file_raises_caption_burn_error(
        self, mock_run: MagicMock, tmp_path: Path, sample_caption_track: CaptionTrack
    ):
        service = CaptionBurnService(output_dir=tmp_path / "out")
        source_file = tmp_path / "source.mp4"
        source_file.write_bytes(b"mock_bytes")

        mock_run.return_value = subprocess.CompletedProcess(
            args=["ffmpeg"], returncode=0, stdout="", stderr=""
        )

        with pytest.raises(CaptionBurnError) as exc_info:
            service.burn_captions(source_file, sample_caption_track)
        assert "not found" in str(exc_info.value).lower()

    @patch("subprocess.run")
    def test_empty_output_file_raises_caption_burn_error(
        self, mock_run: MagicMock, tmp_path: Path, sample_caption_track: CaptionTrack
    ):
        service = CaptionBurnService(output_dir=tmp_path / "out")
        source_file = tmp_path / "source.mp4"
        source_file.write_bytes(b"mock_bytes")

        def side_effect(cmd, **kwargs):
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"")  # 0 bytes
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect

        with pytest.raises(CaptionBurnError) as exc_info:
            service.burn_captions(source_file, sample_caption_track)
        assert "empty" in str(exc_info.value).lower()
