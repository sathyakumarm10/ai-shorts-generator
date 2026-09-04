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

    def extract_short_captions(
        self,
        transcript: TimestampedTranscript,
        start_seconds: float,
        end_seconds: float,
        max_chars_per_line: int = 38,
    ) -> CaptionTrack:
        """Extract, re-base, and format caption segments for a specific Short.

        Args:
            transcript: Source video timestamped transcript.
            start_seconds: Clip start boundary in source seconds.
            end_seconds: Clip end boundary in source seconds.
            max_chars_per_line: Max characters per line for 9:16 readability.

        Returns:
            CaptionTrack: Synchronized, non-overlapping track for the Short.
        """
        if not isinstance(transcript, TimestampedTranscript):
            raise CaptionServiceError(
                f"Expected TimestampedTranscript, got {type(transcript).__name__}"
            )

        s_start = max(0.0, float(start_seconds))
        s_end = float(end_seconds)
        duration = s_end - s_start
        if duration <= 0.05 or not transcript.segments:
            return CaptionTrack(segments=[])

        raw_segments = []
        for seg in transcript.segments:
            if not isinstance(seg, TranscriptSegment):
                continue
            if seg.end_seconds <= s_start or seg.start_seconds >= s_end:
                continue

            clean_text = seg.text.strip()
            if not clean_text:
                continue

            rel_start = max(0.0, seg.start_seconds - s_start)
            rel_end = min(duration, seg.end_seconds - s_start)
            if rel_end <= rel_start + 0.01:
                continue

            raw_segments.append((rel_start, rel_end, clean_text))

        # Split long lines for vertical 9:16 screen readability
        split_segments = []
        for r_start, r_end, text in raw_segments:
            if len(text) <= max_chars_per_line:
                split_segments.append((r_start, r_end, text))
                continue

            words = text.split()
            chunks: List[str] = []
            curr: List[str] = []
            curr_len = 0
            for w in words:
                extra = 1 if curr_len > 0 else 0
                if curr_len + len(w) + extra <= max_chars_per_line:
                    curr.append(w)
                    curr_len += len(w) + extra
                else:
                    if curr:
                        chunks.append(" ".join(curr))
                    curr = [w]
                    curr_len = len(w)
            if curr:
                chunks.append(" ".join(curr))

            if not chunks:
                continue

            seg_dur = r_end - r_start
            total_chars = max(1, sum(len(c) for c in chunks))
            sub_start = r_start
            for idx, chunk in enumerate(chunks):
                chunk_dur = seg_dur * (len(chunk) / total_chars)
                chunk_end = sub_start + chunk_dur
                if idx == len(chunks) - 1:
                    chunk_end = r_end
                if chunk_end > sub_start:
                    split_segments.append((sub_start, chunk_end, chunk))
                sub_start = chunk_end

        final_segments: List[CaptionSegment] = []
        last_end = 0.0
        for cand_start, cand_end, text in split_segments:
            adj_start = max(last_end, cand_start)
            adj_end = max(adj_start + 0.05, cand_end)
            if adj_end > duration:
                adj_end = duration
            if adj_end <= adj_start + 0.02:
                continue

            final_segments.append(
                CaptionSegment(
                    start_seconds=round(adj_start, 3),
                    end_seconds=round(adj_end, 3),
                    text=text,
                )
            )
            last_end = round(adj_end, 3)

        return CaptionTrack(segments=final_segments)
