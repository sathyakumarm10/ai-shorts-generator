"""Unit tests for KaraokeCaptionService ASS subtitle script generation and \k timing tags."""

from pathlib import Path
import pytest

from app.models import CaptionPreset, CaptionSegment, CaptionTrack
from app.services.karaoke_caption_service import (
    KaraokeCaptionService,
    _format_ass_timestamp,
)


class TestKaraokeCaptionService:
    def test_ass_timestamp_formatting(self):
        assert _format_ass_timestamp(0.0) == "0:00:00.00"
        assert _format_ass_timestamp(65.45) == "0:01:05.45"
        assert _format_ass_timestamp(3661.12) == "1:01:01.12"

    def test_generate_ass_script_with_k_tags(self):
        service = KaraokeCaptionService()
        track = CaptionTrack(
            segments=[
                CaptionSegment(start_seconds=1.0, end_seconds=4.0, text="AI generated viral videos"),
            ]
        )
        ass_script = service.generate_ass_script(track, preset=CaptionPreset.KARAOKE)
        assert "[Script Info]" in ass_script
        assert "[V4+ Styles]" in ass_script
        assert "Style: Karaoke" in ass_script
        assert "Dialogue:" in ass_script
        assert "{\\k" in ass_script
        assert "viral" in ass_script

    def test_write_ass_file(self, tmp_path):
        service = KaraokeCaptionService()
        track = CaptionTrack(
            segments=[
                CaptionSegment(start_seconds=0.5, end_seconds=3.5, text="Dynamic social captions"),
            ]
        )
        dest = tmp_path / "subs.ass"
        out_path = service.write_ass_file(track, dest, preset=CaptionPreset.HIGHLIGHT)
        assert out_path.is_file()
        content = out_path.read_text(encoding="utf-8")
        assert "Dynamic" in content
        assert "{\\k" in content
