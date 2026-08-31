r"""Advanced ASS (Advanced SubStation Alpha) Karaoke Caption Generation Service.

Generates synchronized word-by-word active highlighting using ASS `\k` tags.
"""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import List, Optional

from app.models import CaptionPreset, CaptionSegment, CaptionTrack, TimestampedTranscript


@dataclass
class KaraokeStyleConfig:
    """Style configuration for ASS karaoke rendering."""

    font_name: str = "Arial Black"
    font_size: int = 42
    primary_color: str = "&H00FFFFFF"  # Inactive word color (White)
    secondary_color: str = "&H0000D7FF"  # Active highlight color (Bright Yellow/Gold)
    outline_color: str = "&H00000000"  # Black outline
    back_color: str = "&H80000000"  # Shadow
    bold: int = 1
    outline: int = 4
    shadow: int = 2
    alignment: int = 2  # Bottom center
    margin_l: int = 30
    margin_r: int = 30
    margin_v: int = 85


KARAOKE_PRESET_STYLES = {
    CaptionPreset.DEFAULT: KaraokeStyleConfig(
        font_size=42,
        primary_color="&H00FFFFFF",  # White
        secondary_color="&H0000D7FF",  # Gold active
        outline=3,
    ),
    CaptionPreset.KARAOKE: KaraokeStyleConfig(
        font_size=46,
        primary_color="&H00E0E0E0",  # Light grey
        secondary_color="&H0000E5FF",  # Bright Yellow-Orange active
        outline=4,
    ),
    CaptionPreset.CLASSIC_KARAOKE: KaraokeStyleConfig(
        font_size=46,
        primary_color="&H00E0E0E0",
        secondary_color="&H0000E5FF",
        outline=4,
    ),
    CaptionPreset.HIGHLIGHT: KaraokeStyleConfig(
        font_size=44,
        primary_color="&H00FFFFFF",
        secondary_color="&H00FFFF00",  # Electric Cyan active
        outline=4,
    ),
    CaptionPreset.WORD_HIGHLIGHT: KaraokeStyleConfig(
        font_size=44,
        primary_color="&H00FFFFFF",
        secondary_color="&H00FFFF00",
        outline=4,
    ),
    CaptionPreset.BOLD: KaraokeStyleConfig(
        font_size=48,
        primary_color="&H00FFFFFF",
        secondary_color="&H0038BDF8",  # Sky blue active
        outline=5,
        shadow=3,
    ),
    CaptionPreset.PUNCH_POP: KaraokeStyleConfig(
        font_size=48,
        primary_color="&H00FFFFFF",
        secondary_color="&H0038BDF8",
        outline=5,
        shadow=3,
    ),
    CaptionPreset.MINIMAL: KaraokeStyleConfig(
        font_size=36,
        primary_color="&H00D0D0D0",
        secondary_color="&H00FFFFFF",  # White highlight
        outline=2,
        shadow=1,
    ),
    CaptionPreset.CLEAN_CREATOR: KaraokeStyleConfig(
        font_size=36,
        primary_color="&H00D0D0D0",
        secondary_color="&H00FFFFFF",
        outline=2,
        shadow=1,
    ),
}


def _format_ass_timestamp(seconds: float) -> str:
    """Format floating seconds to ASS timestamp: H:MM:SS.cs (centiseconds)."""
    clamped = max(0.0, float(seconds))
    total_cs = int(round(clamped * 100))
    hours = total_cs // 360000
    total_cs %= 360000
    minutes = total_cs // 6000
    total_cs %= 6000
    secs = total_cs // 100
    cs = total_cs % 100
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


class KaraokeCaptionService:
    """Generates ASS karaoke subtitle scripts with word-by-word timing."""

    def get_style_config(self, preset: Optional[CaptionPreset] = None, custom_active_color: Optional[str] = None) -> KaraokeStyleConfig:
        target_preset = preset or CaptionPreset.DEFAULT
        style = KARAOKE_PRESET_STYLES.get(target_preset, KARAOKE_PRESET_STYLES[CaptionPreset.DEFAULT])
        if custom_active_color:
            style = KaraokeStyleConfig(
                font_name=style.font_name,
                font_size=style.font_size,
                primary_color=style.primary_color,
                secondary_color=custom_active_color,
                outline_color=style.outline_color,
                back_color=style.back_color,
                bold=style.bold,
                outline=style.outline,
                shadow=style.shadow,
                alignment=style.alignment,
                margin_l=style.margin_l,
                margin_r=style.margin_r,
                margin_v=style.margin_v,
            )
        return style

    def generate_ass_script(
        self,
        track: CaptionTrack,
        preset: Optional[CaptionPreset] = None,
        custom_active_color: Optional[str] = None,
        max_words_per_line: int = 4,
    ) -> str:
        """Build a complete ASS subtitle script with synchronized karaoke `\\k` tags."""
        style = self.get_style_config(preset, custom_active_color)

        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,{style.font_name},{style.font_size},{style.primary_color},{style.secondary_color},{style.outline_color},{style.back_color},{style.bold},0,0,0,100,100,0,0,1,{style.outline},{style.shadow},{style.alignment},{style.margin_l},{style.margin_r},{style.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        dialogue_lines: List[str] = []

        for seg in track.segments:
            text = seg.text.strip()
            if not text:
                continue

            words = text.split()
            if not words:
                continue

            # Split words into smaller readable dialogue lines (3-5 words)
            chunks: List[List[str]] = []
            cur_chunk: List[str] = []
            for w in words:
                if len(cur_chunk) >= max_words_per_line:
                    chunks.append(cur_chunk)
                    cur_chunk = [w]
                else:
                    cur_chunk.append(w)
            if cur_chunk:
                chunks.append(cur_chunk)

            total_duration = max(0.1, seg.end_seconds - seg.start_seconds)
            total_chars = sum(len(w) for w in words) or 1

            chunk_start = seg.start_seconds
            for ch in chunks:
                ch_chars = sum(len(w) for w in ch)
                ch_duration = total_duration * (ch_chars / total_chars)
                chunk_end = min(seg.end_seconds, chunk_start + ch_duration)

                # Compute word-level karaoke \k durations in centiseconds
                k_parts: List[str] = []
                for word in ch:
                    w_dur_cs = max(10, int(round((len(word) / max(ch_chars, 1)) * (ch_duration * 100))))
                    safe_word = word.replace("{", "\\{").replace("}", "\\}")
                    k_parts.append(f"{{\\k{w_dur_cs}}}{safe_word}")

                line_text = " ".join(k_parts)
                start_str = _format_ass_timestamp(chunk_start)
                end_str = _format_ass_timestamp(chunk_end)

                dialogue_lines.append(f"Dialogue: 0,{start_str},{end_str},Karaoke,,0,0,0,,{line_text}")
                chunk_start = chunk_end

        return header + "\n".join(dialogue_lines) + "\n"

    def write_ass_file(
        self,
        track: CaptionTrack,
        destination_path: Path | str,
        preset: Optional[CaptionPreset] = None,
        custom_active_color: Optional[str] = None,
    ) -> Path:
        """Generate and save an ASS karaoke script to disk."""
        dest = Path(destination_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = self.generate_ass_script(track, preset=preset, custom_active_color=custom_active_color)
        dest.write_text(content, encoding="utf-8")
        return dest
