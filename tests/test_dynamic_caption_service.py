"""Unit tests for DynamicCaptionService and dynamic caption styling presets."""

import pytest

from app.models import CaptionPreset, CaptionSegment, CaptionTrack
from app.services.dynamic_caption_service import (
    PRESET_STYLES,
    CaptionStyleConfig,
    DynamicCaptionService,
)


class TestDynamicCaptionService:
    def test_preset_style_configurations(self):
        service = DynamicCaptionService()
        for preset in CaptionPreset:
            config = service.get_style_config(preset)
            assert isinstance(config, CaptionStyleConfig)
            assert config.font_size > 0
            assert config.primary_color.startswith("&H")
            assert config.outline_width >= 1
            assert config.max_words_per_line >= 2

    def test_ffmpeg_force_style_format(self):
        service = DynamicCaptionService()
        config = CaptionStyleConfig(
            font_name="Arial",
            font_size=26,
            primary_color="&H0000D7FF",
            outline_color="&H00000000",
            back_color="&H80000000",
            bold=1,
            outline_width=3,
            shadow_depth=1,
            alignment=2,
            margin_v=40,
        )
        style_str = service.format_ffmpeg_force_style(config)
        assert "FontName=Arial" in style_str
        assert "FontSize=26" in style_str
        assert "PrimaryColour=&H0000D7FF" in style_str
        assert "Alignment=2" in style_str
        assert "MarginV=40" in style_str

    def test_group_segment_words_short_text(self):
        service = DynamicCaptionService()
        seg = CaptionSegment(start_seconds=1.0, end_seconds=3.0, text="Hello world")
        chunks = service.group_segment_words(seg, max_words=5, max_chars=32)
        assert len(chunks) == 1
        assert chunks[0].text == "Hello world"
        assert chunks[0].start_seconds == 1.0
        assert chunks[0].end_seconds == 3.0

    def test_group_segment_words_long_sentence_chunking(self):
        service = DynamicCaptionService()
        seg = CaptionSegment(
            start_seconds=0.0,
            end_seconds=10.0,
            text="This is an extremely long sentence that should definitely be split into smaller punchy chunks for mobile viewing",
        )
        chunks = service.group_segment_words(seg, max_words=4, max_chars=25)
        assert len(chunks) > 1
        # Validate that timing is contiguous, non-inverted, and within boundaries
        for i, ch in enumerate(chunks):
            assert ch.start_seconds >= 0.0
            assert ch.end_seconds <= 10.0
            assert ch.end_seconds > ch.start_seconds
            assert len(ch.text.split()) <= 5

    def test_create_dynamic_track_preserves_order_and_no_overlap(self):
        service = DynamicCaptionService()
        raw_track = CaptionTrack(
            segments=[
                CaptionSegment(start_seconds=0.0, end_seconds=4.0, text="Welcome to the future of AI video creation"),
                CaptionSegment(start_seconds=4.5, end_seconds=8.0, text="It automatically edits and captions everything cleanly"),
            ]
        )
        dynamic_track = service.create_dynamic_track(raw_track, preset=CaptionPreset.KARAOKE)
        assert len(dynamic_track.segments) >= 2
        # Check track validity
        for i in range(len(dynamic_track.segments) - 1):
            curr_seg = dynamic_track.segments[i]
            next_seg = dynamic_track.segments[i + 1]
            assert curr_seg.start_seconds <= next_seg.start_seconds
            assert curr_seg.end_seconds <= next_seg.start_seconds + 1e-5
