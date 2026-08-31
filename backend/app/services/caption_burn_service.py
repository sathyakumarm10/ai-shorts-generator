"""Caption burn-in service using FFmpeg subtitle filters.

This module provides the `CaptionBurnService` for burning formatted `CaptionTrack`
subtitles directly onto video frames using mobile-readable styling and FFmpeg.
"""

from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Optional
from uuid import uuid4

from app.models import CaptionPreset, CaptionTrack, IngestedVideo
from app.services.caption_service import CaptionService
from app.services.dynamic_caption_service import DynamicCaptionService

# Default output directory for captioned videos, located in ignored `outputs/captioned` area.
DEFAULT_CAPTIONED_OUTPUT_DIR = Path("outputs") / "captioned"


class CaptionBurnError(Exception):
    """Domain exception raised when caption burn-in fails."""

    pass


class CaptionBurnService:
    """Service responsible for burning styled captions into video frames using FFmpeg."""

    # Centralized mobile-optimized subtitle style configuration for 1080x1920 vertical Shorts
    DEFAULT_SUBTITLE_STYLE = (
        "FontSize=24,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Alignment=2,MarginV=35"
    )

    def __init__(
        self,
        output_dir: Path | str = DEFAULT_CAPTIONED_OUTPUT_DIR,
        ffmpeg_executable: str = "ffmpeg",
        caption_service: Optional[CaptionService] = None,
        dynamic_caption_service: Optional[DynamicCaptionService] = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.ffmpeg_executable = ffmpeg_executable
        self.caption_service = caption_service or CaptionService()
        self.dynamic_caption_service = dynamic_caption_service or DynamicCaptionService()

    def burn_captions(
        self,
        video: IngestedVideo | str | Path,
        captions: CaptionTrack,
        output_dir: Optional[Path | str] = None,
        preset: Optional[CaptionPreset] = None,
    ) -> IngestedVideo:
        """Burn styled captions from a CaptionTrack into the video using FFmpeg subtitles filter.

        Args:
            video: IngestedVideo instance or local path to the input video.
            captions: Validated CaptionTrack containing chronological caption segments.
            output_dir: Optional override directory for rendered output file.
            preset: Optional CaptionPreset to apply custom styling and word chunking.

        Returns:
            IngestedVideo: Contains file path to the newly rendered captioned MP4.

        Raises:
            CaptionBurnError: If source video is missing/empty, captions are invalid,
                              FFmpeg rendering fails, or output file is not created.
        """
        # Resolve source video file path
        if isinstance(video, IngestedVideo):
            source_path = Path(video.file_path)
        elif isinstance(video, (str, Path)):
            source_path = Path(video)
        else:
            raise CaptionBurnError(
                f"Invalid video type: expected IngestedVideo, str, or Path, got {type(video).__name__}"
            )

        if not source_path.is_file():
            raise CaptionBurnError(f"Source video file not found: {source_path}")

        try:
            source_size = source_path.stat().st_size
            if source_size <= 0:
                raise CaptionBurnError(f"Source video file is empty (0 bytes): {source_path}")
        except OSError as exc:
            raise CaptionBurnError(f"Could not inspect source video file: {exc}") from exc

        # Validate captions track
        if not isinstance(captions, CaptionTrack):
            raise CaptionBurnError(f"Expected CaptionTrack, got {type(captions).__name__}")

        # Resolve output directory and create if needed
        dest_dir = Path(output_dir) if output_dir is not None else self.output_dir
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Generate unique collision-resistant output filename
        unique_id = uuid4().hex
        output_path = dest_dir / f"captioned_{unique_id}.mp4"

        # Check for FFmpeg executable
        executable = shutil.which(self.ffmpeg_executable) or self.ffmpeg_executable

        # Refine captions track and compute style for the given preset
        target_preset = preset or CaptionPreset.DEFAULT
        try:
            effective_track = self.dynamic_caption_service.create_dynamic_track(captions, preset=target_preset)
            style_config = self.dynamic_caption_service.get_style_config(target_preset)
            force_style_str = self.dynamic_caption_service.format_ffmpeg_force_style(style_config)
        except Exception:
            effective_track = captions
            force_style_str = self.DEFAULT_SUBTITLE_STYLE

        # Create isolated temporary directory for the intermediate SRT file with automatic cleanup
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_srt_path = Path(temp_dir) / "subtitles.srt"
            self.caption_service.write_srt(effective_track, temp_srt_path)

            # Escape path for FFmpeg subtitles filter on Windows / Linux
            # In libavfilter: backslashes become forward slashes and colons must be escaped with \:
            escaped_srt_path = str(temp_srt_path.resolve()).replace("\\", "/").replace(":", "\\:")

            filter_expr = f"subtitles='{escaped_srt_path}':force_style='{force_style_str}'"

            cmd = [
                executable,
                "-y",  # Overwrite output file
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
                raise CaptionBurnError(
                    f"FFmpeg executable '{self.ffmpeg_executable}' not found on system path."
                ) from exc
            except Exception as exc:
                raise CaptionBurnError(f"Failed to execute FFmpeg for caption burning: {exc}") from exc

            if result.returncode != 0:
                err_msg = result.stderr.strip() or "Unknown FFmpeg subtitle error"
                raise CaptionBurnError(f"FFmpeg caption burn-in failed: {err_msg}")

        # Verify generated output file
        if not output_path.is_file():
            raise CaptionBurnError(
                f"FFmpeg completed without error, but captioned video was not found at: {output_path}"
            )

        try:
            output_size = output_path.stat().st_size
            if output_size <= 0:
                raise CaptionBurnError(f"Generated captioned video file is empty (0 bytes): {output_path}")
        except OSError as exc:
            raise CaptionBurnError(f"Could not verify generated captioned video file: {exc}") from exc

        return IngestedVideo(file_path=str(output_path))
