"""Timestamped audio transcription service.

This module provides domain models, provider abstractions, and the
`TranscriptionService` for converting audio from ingested video files into
timestamped transcript segments for downstream highlight analysis.
"""

from abc import ABC, abstractmethod
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Optional

from app.models import IngestedVideo, TimestampedTranscript, TranscriptSegment


class TranscriptionError(Exception):
    """Domain exception raised when audio extraction, transcription, or validation fails."""

    pass


class TranscriptionProvider(ABC):
    """Abstract interface for speech-to-text transcription providers."""

    @abstractmethod
    def transcribe(self, audio_or_video_path: Path) -> TimestampedTranscript:
        """Transcribe an audio or video file into a TimestampedTranscript.

        Args:
            audio_or_video_path: Path to the local audio or video file.

        Returns:
            TimestampedTranscript: Chronologically ordered, non-overlapping transcript segments.

        Raises:
            TranscriptionError: If speech-to-text processing fails.
        """
        pass


class PlaceholderTranscriptionProvider(TranscriptionProvider):
    """Placeholder transcription provider adapter when no live engine is configured.

    Raises a clear TranscriptionError explaining that an operational transcription
    engine (e.g. local Whisper or cloud provider) must be configured.
    """

    def transcribe(self, audio_or_video_path: Path) -> TimestampedTranscript:
        raise TranscriptionError(
            f"No speech-to-text engine is currently active. Please configure an operational "
            f"TranscriptionProvider implementation (e.g. local Whisper or cloud provider) to transcribe '{audio_or_video_path.name}'."
        )


class TranscriptionService:
    """Service responsible for managing audio extraction and transcription."""

    def __init__(
        self,
        provider: Optional[TranscriptionProvider] = None,
        ffmpeg_executable: str = "ffmpeg",
    ) -> None:
        self.provider = provider or PlaceholderTranscriptionProvider()
        self.ffmpeg_executable = ffmpeg_executable

    def extract_audio(
        self,
        video_path: Path,
        output_wav_path: Path,
    ) -> Path:
        """Extract a 16kHz mono WAV audio file from a video using FFmpeg.

        Args:
            video_path: Path to the source video file.
            output_wav_path: Destination path for the extracted WAV audio file.

        Returns:
            Path: Path to the created audio file.

        Raises:
            TranscriptionError: If FFmpeg executable is missing or audio extraction fails.
        """
        if not video_path.is_file():
            raise TranscriptionError(f"Video file not found: {video_path}")

        executable = shutil.which(self.ffmpeg_executable) or self.ffmpeg_executable

        cmd = [
            executable,
            "-y",
            "-i",
            str(video_path),
            "-vn",  # Disable video recording
            "-acodec",
            "pcm_s16le",  # Uncompressed 16-bit PCM WAV
            "-ar",
            "16000",  # Standard 16kHz sample rate for STT engines
            "-ac",
            "1",  # Mono channel
            str(output_wav_path),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise TranscriptionError(
                f"FFmpeg executable '{self.ffmpeg_executable}' not found on system path."
            ) from exc
        except Exception as exc:
            raise TranscriptionError(f"Failed to execute FFmpeg for audio extraction: {exc}") from exc

        if result.returncode != 0:
            err_msg = result.stderr.strip() or "Unknown FFmpeg error"
            raise TranscriptionError(f"FFmpeg audio extraction failed: {err_msg}")

        if not output_wav_path.is_file() or output_wav_path.stat().st_size == 0:
            raise TranscriptionError(f"Extracted audio file was not created or is empty: {output_wav_path}")

        return output_wav_path

    def transcribe(
        self,
        video: IngestedVideo | str | Path,
        extract_audio_first: bool = True,
    ) -> TimestampedTranscript:
        """Transcribe speech from an ingested video into timestamped segments.

        Args:
            video: IngestedVideo model or Path/str to the source video file.
            extract_audio_first: If True, uses FFmpeg to extract a temporary mono WAV audio
                                file for the transcription provider and cleans it up immediately.

        Returns:
            TimestampedTranscript: Validated, chronologically ordered transcript segments.

        Raises:
            TranscriptionError: If input video is missing, extraction fails, or the provider fails.
        """
        if isinstance(video, IngestedVideo):
            video_path = Path(video.file_path)
        else:
            video_path = Path(video)

        if not video_path.is_file():
            raise TranscriptionError(f"Source video file not found: {video_path}")

        if extract_audio_first:
            # Create a temporary directory that is guaranteed to be cleaned up
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_audio_path = Path(temp_dir) / "temp_audio.wav"
                self.extract_audio(video_path, temp_audio_path)
                try:
                    transcript = self.provider.transcribe(temp_audio_path)
                except TranscriptionError:
                    raise
                except Exception as exc:
                    raise TranscriptionError(f"Transcription provider failed: {exc}") from exc
        else:
            try:
                transcript = self.provider.transcribe(video_path)
            except TranscriptionError:
                raise
            except Exception as exc:
                raise TranscriptionError(f"Transcription provider failed: {exc}") from exc

        if not isinstance(transcript, TimestampedTranscript):
            raise TranscriptionError(
                f"Provider returned invalid transcript type: expected TimestampedTranscript, got {type(transcript).__name__}"
            )

        return transcript
