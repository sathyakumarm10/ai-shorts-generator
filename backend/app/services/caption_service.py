"""Timestamped caption generation and SRT formatting service.

This module provides the `CaptionService` for converting `TimestampedTranscript`
data into clean `CaptionTrack` objects and standard formatted `.srt` subtitle files.
"""

from pathlib import Path
from typing import List

from app.models import CaptionSegment, CaptionTrack, TimestampedTranscript, TranscriptSegment


class CaptionServiceError(Exception):
    """Domain exception raised when caption generation or SRT formatting fails."""

    pass


def format_srt_timestamp(seconds: float) -> str:
    """Convert floating-point seconds into standard SRT timestamp format (HH:MM:SS,mmm).

    Args:
        seconds: Non-negative timestamp in seconds.

    Returns:
        str: Formatted time string like '00:01:23,456'.
    """
    total_ms = int(round(seconds * 1000))
    hours = total_ms // 3600000
    total_ms %= 3600000
    minutes = total_ms // 60000
    total_ms %= 60000
    secs = total_ms // 1000
    ms = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


class CaptionService:
    """Service responsible for generating and formatting video captions from transcripts."""

    def from_transcript(self, transcript: TimestampedTranscript) -> CaptionTrack:
        """Convert a TimestampedTranscript into a validated CaptionTrack.

        Args:
            transcript: Input TimestampedTranscript from transcription.

        Returns:
            CaptionTrack: Chronological, non-overlapping caption segments.

        Raises:
            CaptionServiceError: If transcript is invalid or segments cannot be converted.
        """
        if not isinstance(transcript, TimestampedTranscript):
            raise CaptionServiceError(
                f"Expected TimestampedTranscript, got {type(transcript).__name__}"
            )

        caption_segments: List[CaptionSegment] = []
        for idx, seg in enumerate(transcript.segments):
            if not isinstance(seg, TranscriptSegment):
                raise CaptionServiceError(f"Segment {idx} is not a TranscriptSegment: {type(seg).__name__}")

            clean_text = seg.text.strip()
            if not clean_text:
                continue

            try:
                caption_seg = CaptionSegment(
                    start_seconds=seg.start_seconds,
                    end_seconds=seg.end_seconds,
                    text=clean_text,
                )
                caption_segments.append(caption_seg)
            except Exception as exc:
                raise CaptionServiceError(f"Failed to create CaptionSegment {idx}: {exc}") from exc

        try:
            return CaptionTrack(segments=caption_segments)
        except Exception as exc:
            raise CaptionServiceError(f"Failed to construct valid CaptionTrack: {exc}") from exc

    def to_srt(self, track: CaptionTrack) -> str:
        """Convert a CaptionTrack into valid SubRip (SRT) subtitle text.

        Args:
            track: CaptionTrack containing ordered caption segments.

        Returns:
            str: Valid SRT-formatted subtitle content.

        Raises:
            CaptionServiceError: If track is invalid.
        """
        if not isinstance(track, CaptionTrack):
            raise CaptionServiceError(f"Expected CaptionTrack, got {type(track).__name__}")

        if not track.segments:
            return ""

        srt_blocks: List[str] = []
        for idx, seg in enumerate(track.segments, start=1):
            start_str = format_srt_timestamp(seg.start_seconds)
            end_str = format_srt_timestamp(seg.end_seconds)
            srt_blocks.append(f"{idx}\n{start_str} --> {end_str}\n{seg.text.strip()}\n")

        return "\n".join(srt_blocks) + "\n"

    def write_srt(self, track: CaptionTrack, output_path: Path | str) -> Path:
        """Write a CaptionTrack to a specified destination as a UTF-8 SRT file.

        Args:
            track: CaptionTrack instance.
            output_path: Path where the .srt file should be written.

        Returns:
            Path: Path to the generated SRT file.

        Raises:
            CaptionServiceError: If writing the file fails.
        """
        dest_path = Path(output_path)
        try:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            srt_content = self.to_srt(track)
            dest_path.write_text(srt_content, encoding="utf-8")
        except Exception as exc:
            raise CaptionServiceError(f"Failed to write SRT file at '{dest_path}': {exc}") from exc

        if not dest_path.is_file():
            raise CaptionServiceError(f"SRT file was not created at expected path: {dest_path}")

        return dest_path
