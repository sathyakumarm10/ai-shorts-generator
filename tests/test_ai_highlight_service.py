"""Unit and integration tests for AIHighlightService and intelligent candidate generation."""

from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest

from app.models import (
    HighlightCandidate,
    HighlightScore,
    HighlightSource,
    TimestampedTranscript,
    TranscriptSegment,
    VideoMetadata,
    VideoSource,
    VideoSourceType,
)
from app.services.ai_highlight_service import (
    AIHighlightService,
    BaseAIProvider,
    OpenRouterAIProvider,
)
from app.services.shorts_generation_service import ShortsGenerationService


class MockAIProvider(BaseAIProvider):
    """Test mock provider returning pre-configured highlight candidate dicts."""

    def __init__(self, response: Optional[List[Dict[str, Any]]] = None, should_fail: bool = False):
        self.response = response
        self.should_fail = should_fail
        self.call_count = 0

    def generate_highlights(
        self,
        transcript: TimestampedTranscript,
        min_duration: float,
        max_duration: float,
        target_duration: float,
        max_clips: int,
        timeout_seconds: float = 15.0,
    ) -> Optional[List[Dict[str, Any]]]:
        self.call_count += 1
        if self.should_fail:
            raise RuntimeError("LLM API network error simulation")
        return self.response


@pytest.fixture
def sample_transcript() -> TimestampedTranscript:
    segments = [
        TranscriptSegment(start_seconds=0.0, end_seconds=10.0, text="Welcome everyone to today's deep dive session."),
        TranscriptSegment(start_seconds=10.0, end_seconds=25.0, text="Here is the single most important secret to success."),
        TranscriptSegment(start_seconds=25.0, end_seconds=45.0, text="When you focus on consistency, compounding momentum takes over."),
        TranscriptSegment(start_seconds=45.0, end_seconds=65.0, text="That is how top performers achieve 10x better results."),
        TranscriptSegment(start_seconds=65.0, end_seconds=80.0, text="Thank you for watching and see you next time."),
    ]
    return TimestampedTranscript(segments=segments, full_text=" ".join(s.text for s in segments))


def test_ai_candidate_valid_extraction(sample_transcript):
    mock_response = [
        {
            "start_seconds": 10.0,
            "end_seconds": 45.0,
            "title": "The Secret to Massive Success",
            "viral_hook": "This one habit will change everything for you...",
            "description": "Focusing on consistency and momentum compounding.",
            "reasoning": "Strong hook and inspiring conclusion.",
            "score": {
                "overall": 0.96,
                "hook": 0.95,
                "emotion": 0.88,
                "curiosity": 0.92,
                "information_density": 0.85,
            },
        }
    ]
    provider = MockAIProvider(response=mock_response)
    service = AIHighlightService(provider=provider)

    candidates = service.generate_ai_candidates(
        transcript=sample_transcript,
        min_duration=30.0,
        max_duration=60.0,
        target_duration=35.0,
        max_clips=2,
    )

    assert len(candidates) == 1
    c = candidates[0]
    assert c.start_seconds == 10.0
    assert c.end_seconds == 45.0
    assert c.duration_seconds == 35.0
    assert c.title == "The Secret to Massive Success"
    assert c.viral_hook == "This one habit will change everything for you..."
    assert c.source_type == HighlightSource.AI
    assert c.score.overall == 0.96


def test_ai_candidate_invalid_timestamps_rejected(sample_transcript):
    mock_response = [
        {
            # End earlier than start
            "start_seconds": 40.0,
            "end_seconds": 20.0,
            "title": "Impossible inverted clip",
        },
        {
            # Negative timestamp
            "start_seconds": -5.0,
            "end_seconds": 30.0,
            "title": "Negative start clip",
        },
        {
            # Out of bounds (> video duration)
            "start_seconds": 70.0,
            "end_seconds": 150.0,
            "title": "Way too long",
        },
        {
            # Clip duration way too short (< 30s min limit)
            "start_seconds": 10.0,
            "end_seconds": 15.0,
            "title": "5s clip",
        },
    ]
    provider = MockAIProvider(response=mock_response)
    service = AIHighlightService(provider=provider)

    candidates = service.generate_ai_candidates(
        transcript=sample_transcript,
        min_duration=30.0,
        max_duration=60.0,
        target_duration=35.0,
        video_duration=80.0,
    )

    # All invalid candidates should be discarded
    assert len(candidates) == 0


def test_ai_failure_graceful_empty_return(sample_transcript):
    provider = MockAIProvider(should_fail=True)
    service = AIHighlightService(provider=provider)

    candidates = service.generate_ai_candidates(transcript=sample_transcript)
    assert candidates == []


def test_unconfigured_openrouter_provider_returns_none(sample_transcript, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    provider = OpenRouterAIProvider(api_key=None)
    assert not provider.is_available()
    res = provider.generate_highlights(sample_transcript, 30.0, 60.0, 45.0, 1)
    assert res is None
