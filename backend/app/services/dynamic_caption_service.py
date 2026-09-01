"""Dynamic social-media styled caption service for 9:16 vertical Shorts.

This module provides:
1. `CaptionStyleConfig`: Settings for font size, colors, outlines, line breaking, and margins.
2. `DynamicCaptionService`: Breaks long sentences into punchy, mobile-readable 3-5 word groups,
   computes exact timing windows, generates FFmpeg ASS/SRT subtitle styling for presets:
   - default: Clean white text with dark outline and comfortable margins
   - karaoke: High-energy pop style with glowing yellow/gold primary text
   - highlight: Vibrant cyan primary text with thick bold stroke
   - bold: High-impact heavy white text with extra-thick dark border and shadow
   - minimal: Elegant understated white text with soft shadow and subtle outline
"""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import List, Optional, Tuple

from app.models import CaptionPreset, CaptionSegment, CaptionTrack


@dataclass
class CaptionStyleConfig:
    """Style configuration for dynamic caption rendering."""

    font_name: str = "Arial"
    font_size: int = 24
    primary_color: str = "&H00FFFFFF"  # BGR + Alpha in ASS format (&HAABBGGRR / &H00BBGGRR)
    outline_color: str = "&H00000000"
    back_color: str = "&H80000000"
    bold: int = 1
    outline_width: int = 2
    shadow_depth: int = 1
    alignment: int = 2  # Bottom-Center (Numpad layout: 2 = bottom-center)
    margin_v: int = 35
    max_words_per_line: int = 5
    max_chars_per_line: int = 32


# Style dictionary for each preset
PRESET_STYLES = {
    CaptionPreset.DEFAULT: CaptionStyleConfig(
        font_size=24,
        primary_color="&H00FFFFFF",  # White
        outline_color="&H00000000",  # Black
        outline_width=2,
        bold=1,
        alignment=2,
        margin_v=35,
        max_words_per_line=5,
    ),
    CaptionPreset.KARAOKE: CaptionStyleConfig(
        font_size=26,
        primary_color="&H0000D7FF",  # Gold / Bright Yellow
        outline_color="&H00000000",  # Black
        outline_width=3,
        bold=1,
        alignment=2,
        margin_v=40,
        max_words_per_line=4,
    ),
    CaptionPreset.HIGHLIGHT: CaptionStyleConfig(
        font_size=25,
        primary_color="&H00FFFF00",  # Bright Cyan
        outline_color="&H00000000",  # Black
        outline_width=3,
        bold=1,
        alignment=2,
        margin_v=38,
        max_words_per_line=4,
    ),
    CaptionPreset.BOLD: CaptionStyleConfig(
        font_size=28,
        primary_color="&H00FFFFFF",  # White
        outline_color="&H00000000",  # Black
        outline_width=4,
        bold=1,
        shadow_depth=2,
        alignment=2,
        margin_v=42,
        max_words_per_line=3,
    ),
    CaptionPreset.CLASSIC_KARAOKE: CaptionStyleConfig(
        font_size=26,
        primary_color="&H0000D7FF",
        outline_color="&H00000000",
        outline_width=3,
        bold=1,
        alignment=2,
        margin_v=40,
        max_words_per_line=4,
    ),
    CaptionPreset.WORD_HIGHLIGHT: CaptionStyleConfig(
        font_size=25,
        primary_color="&H00FFFF00",
        outline_color="&H00000000",
        outline_width=3,
        bold=1,
        alignment=2,
        margin_v=38,
        max_words_per_line=4,
    ),
    CaptionPreset.PUNCH_POP: CaptionStyleConfig(
        font_size=28,
        primary_color="&H00FFFFFF",
        outline_color="&H00000000",
        outline_width=4,
        bold=1,
        shadow_depth=2,
        alignment=2,
        margin_v=42,
        max_words_per_line=3,
    ),
    CaptionPreset.MINIMAL: CaptionStyleConfig(
        font_size=20,
        primary_color="&H00F0F0F0",  # Soft white
        outline_color="&H00111111",  # Dark grey
        outline_width=1,
        bold=0,
        shadow_depth=1,
        alignment=2,
        margin_v=30,
        max_words_per_line=6,
    ),
    CaptionPreset.CLEAN_CREATOR: CaptionStyleConfig(
        font_size=20,
        primary_color="&H00F0F0F0",
        outline_color="&H00111111",
        outline_width=1,
        bold=0,
        shadow_depth=1,
        alignment=2,
        margin_v=30,
        max_words_per_line=6,
    ),
}


class DynamicCaptionService:
    """Provides word-level segmentation, line breaking, and styled subtitle filters."""

    @staticmethod
    def get_style_config(preset: Optional[CaptionPreset] = None) -> CaptionStyleConfig:
        """Retrieve the style configuration for the specified preset."""
        p = preset or CaptionPreset.DEFAULT
        return PRESET_STYLES.get(p, PRESET_STYLES[CaptionPreset.DEFAULT])

    @staticmethod
    def format_ffmpeg_force_style(config: CaptionStyleConfig) -> str:
        """Convert a CaptionStyleConfig into an FFmpeg subtitles force_style string."""
        return (
            f"FontName={config.font_name},"
            f"FontSize={config.font_size},"
            f"PrimaryColour={config.primary_color},"
            f"OutlineColour={config.outline_color},"
            f"BackColour={config.back_color},"
            f"Bold={config.bold},"
            f"Outline={config.outline_width},"
            f"Shadow={config.shadow_depth},"
            f"Alignment={config.alignment},"
            f"MarginV={config.margin_v}"
        )

    def group_segment_words(
        self,
        segment: CaptionSegment,
        max_words: int = 5,
        max_chars: int = 32,
    ) -> List[CaptionSegment]:
        """Break a long sentence/segment into punchy, short subtitle chunks with proportional timing."""
        clean_text = segment.text.strip()
        if not clean_text:
            return []

        words = clean_text.split()
        if len(words) <= max_words and len(clean_text) <= max_chars:
            return [segment]

        # Group words into chunks
        chunks: List[List[str]] = []
        current_chunk: List[str] = []
        current_len = 0

        for word in words:
            word_len = len(word)
            if current_chunk and (len(current_chunk) >= max_words or current_len + word_len + 1 > max_chars):
                chunks.append(current_chunk)
                current_chunk = [word]
                current_len = word_len
            else:
                current_chunk.append(word)
                current_len += (word_len + 1) if current_chunk else word_len

        if current_chunk:
            chunks.append(current_chunk)

        if not chunks:
            return [segment]

        # Distribute timing proportionally based on character counts
        total_duration = max(0.01, segment.end_seconds - segment.start_seconds)
        total_chars = sum(sum(len(w) for w in ch) for ch in chunks)
        if total_chars <= 0:
            total_chars = 1

        result_segments: List[CaptionSegment] = []
        cur_start = segment.start_seconds

        for i, ch in enumerate(chunks):
            ch_chars = sum(len(w) for w in ch)
            fraction = ch_chars / total_chars
            ch_duration = total_duration * fraction

            if i == len(chunks) - 1:
                cur_end = segment.end_seconds
            else:
                cur_end = round(cur_start + ch_duration, 3)

            # Ensure valid bounds
            cur_end = max(cur_start + 0.05, cur_end)
            if cur_end > segment.end_seconds:
                cur_end = segment.end_seconds

            text_chunk = " ".join(ch)
            result_segments.append(
                CaptionSegment(
                    start_seconds=cur_start,
                    end_seconds=cur_end,
                    text=text_chunk,
                )
            )
            cur_start = cur_end

        return result_segments

    def create_dynamic_track(
        self,
        raw_track: CaptionTrack,
        preset: Optional[CaptionPreset] = None,
    ) -> CaptionTrack:
        """Create a refined CaptionTrack with short word groups matching the chosen preset."""
        config = self.get_style_config(preset)
        new_segments: List[CaptionSegment] = []

        for seg in raw_track.segments:
            grouped = self.group_segment_words(
                seg,
                max_words=config.max_words_per_line,
                max_chars=config.max_chars_per_line,
            )
            for g in grouped:
                # Discard zero-length or inverted segments safely
                if g.end_seconds > g.start_seconds and g.text.strip():
                    new_segments.append(g)

        # Enforce strict chronology and zero overlap
        clean_ordered: List[CaptionSegment] = []
        last_end = 0.0
        for seg in new_segments:
            s = max(last_end, seg.start_seconds)
            e = max(s + 0.05, seg.end_seconds)
            clean_ordered.append(CaptionSegment(start_seconds=s, end_seconds=e, text=seg.text))
            last_end = e

        return CaptionTrack(segments=clean_ordered)
