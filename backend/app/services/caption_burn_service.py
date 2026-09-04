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
from app.services.acceleration_service import HardwareAccelerationService, default_acceleration_service
from app.services.caption_service import CaptionService
from app.services.dynamic_caption_service import DynamicCaptionService
from app.services.karaoke_caption_service import KaraokeCaptionService

# Default output directory for captioned videos, located in ignored `outputs/captioned` area.
DEFAULT_CAPTIONED_OUTPUT_DIR = Path("outputs") / "captioned"


class CaptionBurnError(Exception):
    """Domain exception raised when caption burn-in fails."""

    pass


class CaptionBurnService:
    """Service responsible for burning styled captions into video frames using FFmpeg."""

    DEFAULT_SUBTITLE_STYLE = (
        "FontSize=24,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Alignment=2,MarginV=35"
    )

    def __init__(
        self,
        output_dir: Path | str = DEFAULT_CAPTIONED_OUTPUT_DIR,
        ffmpeg_executable: str = "ffmpeg",
        caption_service: Optional[CaptionService] = None,
        dynamic_caption_service: Optional[DynamicCaptionService] = None,
        karaoke_caption_service: Optional[KaraokeCaptionService] = None,
        acceleration_service: Optional[HardwareAccelerationService] = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.ffmpeg_executable = ffmpeg_executable
        self.caption_service = caption_service or CaptionService()
        self.dynamic_caption_service = dynamic_caption_service or DynamicCaptionService()
        self.karaoke_caption_service = karaoke_caption_service or KaraokeCaptionService()
        self.acceleration_service = acceleration_service or default_acceleration_service

    def burn_captions(
        self,
        video: IngestedVideo | str | Path,
        captions: CaptionTrack,
        output_dir: Optional[Path | str] = None,
        preset: Optional[CaptionPreset] = None,
        enable_karaoke: bool = False,
        karaoke_active_color: Optional[str] = None,
        output_filename: Optional[str] = None,
    ) -> IngestedVideo:
        """Burn styled or animated karaoke captions from a CaptionTrack into video using FFmpeg.

        Args:
            video: IngestedVideo instance or local path to the input video.
            captions: Validated CaptionTrack containing chronological caption segments.
            output_dir: Optional override directory for rendered output file.
            preset: Optional CaptionPreset to apply custom styling and word chunking.
            enable_karaoke: Whether to render animated ASS karaoke subtitles.
            karaoke_active_color: Optional custom active highlight color in ASS hex.
            output_filename: Optional custom output filename.

        Returns:
            IngestedVideo: Contains file path to the newly rendered captioned MP4.
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

        if not isinstance(captions, CaptionTrack):
            raise CaptionBurnError(f"Expected CaptionTrack, got {type(captions).__name__}")

        dest_dir = Path(output_dir) if output_dir is not None else self.output_dir
        dest_dir.mkdir(parents=True, exist_ok=True)

        if output_filename:
            output_path = dest_dir / output_filename
        else:
            unique_id = uuid4().hex
            output_path = dest_dir / f"captioned_{unique_id}.mp4"
        executable = shutil.which(self.ffmpeg_executable) or self.ffmpeg_executable

        target_preset = preset or CaptionPreset.DEFAULT

        def validator() -> bool:
            return output_path.is_file() and output_path.stat().st_size > 0

        # Try ASS karaoke burn-in first if enabled
        if enable_karaoke:
            try:
                with tempfile.TemporaryDirectory() as temp_dir:
                    temp_ass_path = Path(temp_dir) / "subtitles.ass"
                    self.karaoke_caption_service.write_ass_file(
                        track=captions,
                        destination_path=temp_ass_path,
                        preset=target_preset,
                        custom_active_color=karaoke_active_color,
                    )
                    escaped_ass_path = str(temp_ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
                    filter_expr = f"ass='{escaped_ass_path}'"

                    def build_ass_cmd(use_nvenc: bool) -> list[str]:
                        v_flags = ["-c:v", "h264_nvenc", "-preset", "p4"] if use_nvenc else ["-c:v", "libx264"]
                        return [
                            executable,
                            "-y",
                            "-i",
                            str(source_path),
                            "-vf",
                            filter_expr,
                            *v_flags,
                            "-c:a",
                            "aac",
                            "-pix_fmt",
                            "yuv420p",
                            "-movflags",
                            "+faststart",
                            str(output_path),
                        ]

                    res = self.acceleration_service.run_ffmpeg_with_fallback(
                        command_builder=build_ass_cmd,
                        output_file_validator=validator,
                        ffmpeg_executable=self.ffmpeg_executable,
                    )
                    if res.returncode == 0 and validator():
                        return IngestedVideo(file_path=str(output_path))
            except Exception:
                # Automatic fallback to standard SRT/dynamic caption rendering
                pass

        # Standard / fallback SRT subtitle burn-in
        try:
            effective_track = self.dynamic_caption_service.create_dynamic_track(captions, preset=target_preset)
            style_config = self.dynamic_caption_service.get_style_config(target_preset)
            force_style_str = self.dynamic_caption_service.format_ffmpeg_force_style(style_config)
        except Exception:
            effective_track = captions
            force_style_str = self.DEFAULT_SUBTITLE_STYLE

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_srt_path = Path(temp_dir) / "subtitles.srt"
            self.caption_service.write_srt(effective_track, temp_srt_path)

            escaped_srt_path = str(temp_srt_path.resolve()).replace("\\", "/").replace(":", "\\:")
            filter_expr = f"subtitles='{escaped_srt_path}':force_style='{force_style_str}'"

            def build_srt_cmd(use_nvenc: bool) -> list[str]:
                v_flags = ["-c:v", "h264_nvenc", "-preset", "p4"] if use_nvenc else ["-c:v", "libx264"]
                return [
                    executable,
                    "-y",
                    "-i",
                    str(source_path),
                    "-vf",
                    filter_expr,
                    *v_flags,
                    "-c:a",
                    "aac",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(output_path),
                ]

            try:
                result = self.acceleration_service.run_ffmpeg_with_fallback(
                    command_builder=build_srt_cmd,
                    output_file_validator=validator,
                    ffmpeg_executable=self.ffmpeg_executable,
                )
            except FileNotFoundError as exc:
                raise CaptionBurnError(f"FFmpeg executable '{self.ffmpeg_executable}' not found on system path.") from exc
            except Exception as exc:
                raise CaptionBurnError(f"Failed to execute FFmpeg for caption burning: {exc}") from exc

            if result.returncode != 0:
                err_msg = result.stderr.strip() or "Unknown FFmpeg subtitle error"
                raise CaptionBurnError(f"FFmpeg caption burn-in failed: {err_msg}")

        if not validator():
            raise CaptionBurnError(f"Generated captioned video was not found or is empty at: {output_path}")

        return IngestedVideo(file_path=str(output_path))
