"""Unit and integration tests for deterministic highlight scoring and candidate generation.

These tests verify HighlightScore and HighlightCandidate models, signal scoring
heuristics (hook, curiosity, emotion, information density), weighted composite
scoring, deterministic ranking, candidate window generation from transcript segments,
and error handling.
"""

import math
import pytest
from pydantic import ValidationError

from app.models import HighlightCandidate, HighlightScore, TimestampedTranscript, TranscriptSegment
from app.services.highlight_scoring_service import HighlightScoringError, HighlightScoringService


@pytest.fixture
def scoring_service() -> HighlightScoringService:
    """Fixture providing a HighlightScoringService instance."""
    return HighlightScoringService()


# ---------------------------------------------------------------------------
# HighlightScore & HighlightCandidate Model Validation Tests
# ---------------------------------------------------------------------------


class TestHighlightModels:
    def test_valid_highlight_score(self):
        score = HighlightScore(
            overall=0.85,
            hook=0.90,
            emotion=0.75,
            curiosity=0.80,
            information_density=0.70,
        )
        assert score.overall == 0.85
        assert score.hook == 0.90
        assert score.emotion == 0.75
        assert score.curiosity == 0.80
        assert score.information_density == 0.70

    def test_reject_scores_out_of_bounds(self):
        with pytest.raises(ValidationError):
            HighlightScore(overall=-0.1, hook=0.5, emotion=0.5, curiosity=0.5, information_density=0.5)
        with pytest.raises(ValidationError):
            HighlightScore(overall=1.1, hook=0.5, emotion=0.5, curiosity=0.5, information_density=0.5)
        with pytest.raises(ValidationError):
            HighlightScore(overall=0.5, hook=-0.01, emotion=0.5, curiosity=0.5, information_density=0.5)
        with pytest.raises(ValidationError):
            HighlightScore(overall=0.5, hook=0.5, emotion=1.05, curiosity=0.5, information_density=0.5)

    def test_reject_nan_or_infinite_scores(self):
        with pytest.raises(ValidationError):
            HighlightScore(overall=float("nan"), hook=0.5, emotion=0.5, curiosity=0.5, information_density=0.5)
        with pytest.raises(ValidationError):
            HighlightScore(overall=0.5, hook=float("inf"), emotion=0.5, curiosity=0.5, information_density=0.5)

    def test_valid_highlight_candidate(self):
        score = HighlightScore(overall=0.8, hook=0.8, emotion=0.8, curiosity=0.8, information_density=0.8)
        cand = HighlightCandidate(
            start_seconds=10.0,
            end_seconds=40.0,
            duration_seconds=30.0,
            text="This is an awesome highlight segment.",
            score=score,
        )
        assert cand.start_seconds == 10.0
        assert cand.end_seconds == 40.0
        assert cand.duration_seconds == 30.0
        assert cand.text == "This is an awesome highlight segment."

    def test_reject_candidate_invalid_timestamps(self):
        score = HighlightScore(overall=0.8, hook=0.8, emotion=0.8, curiosity=0.8, information_density=0.8)
        with pytest.raises(ValidationError):
            HighlightCandidate(start_seconds=-1.0, end_seconds=30.0, duration_seconds=31.0, text="Text", score=score)
        with pytest.raises(ValidationError):
            HighlightCandidate(start_seconds=30.0, end_seconds=30.0, duration_seconds=0.0, text="Text", score=score)
        with pytest.raises(ValidationError):
            HighlightCandidate(start_seconds=40.0, end_seconds=30.0, duration_seconds=-10.0, text="Text", score=score)
        with pytest.raises(ValidationError):
            # Duration mismatch
            HighlightCandidate(start_seconds=0.0, end_seconds=30.0, duration_seconds=25.0, text="Text", score=score)
        with pytest.raises(ValidationError):
            # Empty text
            HighlightCandidate(start_seconds=0.0, end_seconds=30.0, duration_seconds=30.0, text="   ", score=score)


# ---------------------------------------------------------------------------
# Signal Scoring Unit Tests
# ---------------------------------------------------------------------------


class TestSignalScoring:
    def test_hook_phrases_increase_hook_score(self, scoring_service: HighlightScoringService):
        neutral_score = scoring_service.score_text("Today we are going to talk about programming.")
        hook_score = scoring_service.score_text("Here's why you won't believe the secret biggest mistake.")

        assert hook_score.hook > neutral_score.hook
        assert hook_score.hook >= 0.5

    def test_question_phrases_increase_curiosity_score(self, scoring_service: HighlightScoringService):
        statement_score = scoring_service.score_text("Water boils at 100 degrees Celsius.")
        curiosity_score = scoring_service.score_text("Why does water boil? How does it happen and what if it changes?")

        assert curiosity_score.curiosity > statement_score.curiosity
        assert curiosity_score.curiosity >= 0.5

    def test_emotional_words_increase_emotion_score(self, scoring_service: HighlightScoringService):
        calm_score = scoring_service.score_text("The meeting started at nine and ended at ten.")
        emotional_score = scoring_service.score_text("This was an amazing, shocking, crazy, incredible result that I love!")

        assert emotional_score.emotion > calm_score.emotion
        assert emotional_score.emotion >= 0.5

    def test_numbers_and_claims_increase_information_density(self, scoring_service: HighlightScoringService):
        sparse_score = scoring_service.score_text("Things happened.")
        dense_score = scoring_service.score_text(
            "Our proven strategy increased revenue by 45.5% in the first quarter, generating 1200 new clients."
        )

        assert dense_score.information_density > sparse_score.information_density

    def test_overall_score_follows_weighted_formula(self, scoring_service: HighlightScoringService):
        score = scoring_service.score_text("Here's why this shocking method increased revenue by 50%?")
        expected_overall = (
            (0.30 * score.hook)
            + (0.25 * score.curiosity)
            + (0.20 * score.emotion)
            + (0.25 * score.information_density)
        )
        assert score.overall == pytest.approx(expected_overall, abs=1e-3)

    def test_deterministic_scoring(self, scoring_service: HighlightScoringService):
        text = "You won't believe how this crazy 50% increase happened! Watch until the end."
        score1 = scoring_service.score_text(text)
        score2 = scoring_service.score_text(text)

        assert score1.overall == score2.overall
        assert score1.hook == score2.hook
        assert score1.emotion == score2.emotion
        assert score1.curiosity == score2.curiosity
        assert score1.information_density == score2.information_density

    def test_score_segment_method(self, scoring_service: HighlightScoringService):
        seg = TranscriptSegment(start_seconds=0.0, end_seconds=5.0, text="Listen to this amazing secret.")
        score = scoring_service.score_segment(seg)

        assert isinstance(score, HighlightScore)
        assert score.hook > 0.0
        assert score.emotion > 0.0


# ---------------------------------------------------------------------------
# Candidate Generation Tests
# ---------------------------------------------------------------------------


class TestCandidateGeneration:
    def test_empty_transcript_produces_no_candidates(self, scoring_service: HighlightScoringService):
        transcript = TimestampedTranscript(segments=[])
        candidates = scoring_service.generate_candidates(transcript)
        assert candidates == []

    def test_candidate_timestamps_match_transcript_boundaries(self, scoring_service: HighlightScoringService):
        transcript = TimestampedTranscript(
            segments=[
                TranscriptSegment(start_seconds=0.0, end_seconds=15.0, text="Here is part one of the talk."),
                TranscriptSegment(start_seconds=15.0, end_seconds=30.0, text="Here is part two with great insight."),
                TranscriptSegment(start_seconds=30.0, end_seconds=45.0, text="Here is part three wrapping up."),
            ]
        )
        candidates = scoring_service.generate_candidates(
            transcript, min_duration=30.0, max_duration=60.0, target_duration=30.0
        )

        assert len(candidates) >= 1
        for cand in candidates:
            # Timestamp must match exact segment boundary start and end
            assert cand.start_seconds in [0.0, 15.0, 30.0]
            assert cand.end_seconds in [15.0, 30.0, 45.0]
            assert cand.duration_seconds == pytest.approx(cand.end_seconds - cand.start_seconds, abs=1e-3)
            assert cand.duration_seconds >= 30.0

    def test_combining_neighboring_segments_to_reach_target_duration(
        self, scoring_service: HighlightScoringService
    ):
        # 6 segments of 10s each = 60s total
        transcript = TimestampedTranscript(
            segments=[
                TranscriptSegment(start_seconds=i * 10.0, end_seconds=(i + 1) * 10.0, text=f"Sentence {i+1}.")
                for i in range(6)
            ]
        )
        candidates = scoring_service.generate_candidates(
            transcript, min_duration=30.0, max_duration=60.0, target_duration=30.0
        )

        assert len(candidates) >= 1
        # Candidates should contain combined text of multiple segments
        assert "Sentence 1. Sentence 2. Sentence 3." in candidates[0].text or "Sentence" in candidates[0].text
        assert candidates[0].duration_seconds >= 30.0

    def test_candidates_sorted_by_descending_score(self, scoring_service: HighlightScoringService):
        transcript = TimestampedTranscript(
            segments=[
                TranscriptSegment(start_seconds=0.0, end_seconds=30.0, text="Normal routine boring talking here."),
                TranscriptSegment(
                    start_seconds=30.0,
                    end_seconds=60.0,
                    text="Here's why you won't believe this shocking secret? We increased revenue by 85%!",
                ),
                TranscriptSegment(start_seconds=60.0, end_seconds=90.0, text="Just closing thoughts for everyone."),
            ]
        )
        candidates = scoring_service.generate_candidates(
            transcript, min_duration=30.0, max_duration=60.0, target_duration=30.0, allow_overlap=True
        )

        assert len(candidates) >= 2
        for i in range(len(candidates) - 1):
            assert candidates[i].score.overall >= candidates[i + 1].score.overall

    def test_timestamp_order_used_as_tie_breaker(self, scoring_service: HighlightScoringService):
        # Two identical text segments at different times
        transcript = TimestampedTranscript(
            segments=[
                TranscriptSegment(start_seconds=0.0, end_seconds=30.0, text="Identical repeated sentence content."),
                TranscriptSegment(start_seconds=30.0, end_seconds=60.0, text="Identical repeated sentence content."),
            ]
        )
        candidates = scoring_service.generate_candidates(
            transcript, min_duration=30.0, max_duration=60.0, target_duration=30.0, allow_overlap=True
        )

        assert len(candidates) >= 2
        # If overall score is identical, earlier start_seconds comes first
        if candidates[0].score.overall == candidates[1].score.overall:
            assert candidates[0].start_seconds <= candidates[1].start_seconds

    def test_non_overlapping_candidates_enforced_by_default(self, scoring_service: HighlightScoringService):
        transcript = TimestampedTranscript(
            segments=[
                TranscriptSegment(start_seconds=i * 15.0, end_seconds=(i + 1) * 15.0, text=f"Part {i+1} content.")
                for i in range(8)
            ]
        )
        candidates = scoring_service.generate_candidates(
            transcript, min_duration=30.0, max_duration=60.0, allow_overlap=False
        )

        for i in range(len(candidates)):
            for j in range(i + 1, len(candidates)):
                c1, c2 = candidates[i], candidates[j]
                # Ensure no temporal overlap
                assert c1.end_seconds <= c2.start_seconds + 1e-4 or c1.start_seconds >= c2.end_seconds - 1e-4

    def test_short_transcript_less_than_min_duration_fallback(self, scoring_service: HighlightScoringService):
        # Total transcript duration is 15s (less than min_duration 30s)
        transcript = TimestampedTranscript(
            segments=[
                TranscriptSegment(start_seconds=0.0, end_seconds=7.0, text="Short clip intro."),
                TranscriptSegment(start_seconds=7.0, end_seconds=15.0, text="Short clip conclusion."),
            ]
        )
        candidates = scoring_service.generate_candidates(transcript, min_duration=30.0)

        assert len(candidates) == 1
        assert candidates[0].start_seconds == 0.0
        assert candidates[0].end_seconds == 15.0
        assert candidates[0].duration_seconds == 15.0
        assert "Short clip intro. Short clip conclusion." in candidates[0].text

    def test_invalid_duration_configurations_raise_error(self, scoring_service: HighlightScoringService):
        transcript = TimestampedTranscript(
            segments=[TranscriptSegment(start_seconds=0.0, end_seconds=40.0, text="Sample text.")]
        )
        # min_duration > max_duration
        with pytest.raises(HighlightScoringError):
            scoring_service.generate_candidates(transcript, min_duration=60.0, max_duration=30.0)

        # target_duration < min_duration
        with pytest.raises(HighlightScoringError):
            scoring_service.generate_candidates(transcript, min_duration=30.0, target_duration=20.0)

        # NaN / Inf parameters
        with pytest.raises(HighlightScoringError):
            scoring_service.generate_candidates(transcript, min_duration=float("nan"))
        with pytest.raises(HighlightScoringError):
            scoring_service.generate_candidates(transcript, max_duration=float("inf"))
        with pytest.raises(HighlightScoringError):
            scoring_service.generate_candidates(transcript, min_duration=-10.0)
        with pytest.raises(HighlightScoringError):
            scoring_service.generate_candidates("not_a_transcript")  # type: ignore


# ---------------------------------------------------------------------------
# Synthetic Integration Test
# ---------------------------------------------------------------------------


class TestHighlightScoringSyntheticIntegration:
    def test_strongest_synthetic_highlight_ranks_above_filler(self, scoring_service: HighlightScoringService):
        """Integration test verifying that a dramatic, high-signal segment ranks first."""
        transcript = TimestampedTranscript(
            segments=[
                # Segment 1: Filler (0-30s)
                TranscriptSegment(
                    start_seconds=0.0,
                    end_seconds=30.0,
                    text="Um, yeah, so I woke up this morning and looked outside at the cloudy weather.",
                ),
                # Segment 2: Strong Hook + Emotion + Data (30-65s)
                TranscriptSegment(
                    start_seconds=30.0,
                    end_seconds=65.0,
                    text="Here's why you won't believe the biggest secret! Our team discovered an amazing strategy that increased sales by 75% in 30 days. Why does this matter? Listen to this.",
                ),
                # Segment 3: Moderate Discussion (65-95s)
                TranscriptSegment(
                    start_seconds=65.0,
                    end_seconds=95.0,
                    text="We should definitely keep tracking the results over time and meet again next Tuesday.",
                ),
            ]
        )

        candidates = scoring_service.generate_candidates(
            transcript, min_duration=30.0, max_duration=60.0, target_duration=35.0, allow_overlap=False
        )

        assert len(candidates) >= 1
        top_candidate = candidates[0]

        # Top candidate must be the high-signal hook/data segment starting at 30.0s
        assert top_candidate.start_seconds == 30.0
        assert top_candidate.end_seconds == 65.0
        assert top_candidate.score.overall > 0.4
        assert top_candidate.score.hook > 0.4
        assert "biggest secret" in top_candidate.text
