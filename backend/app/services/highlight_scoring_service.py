"""Deterministic highlight scoring and candidate generation service.

This module provides the `HighlightScoringService` for analyzing
`TimestampedTranscript` segments, calculating multi-dimensional heuristic
interest scores (hook, curiosity, emotion, information density), and generating
ranked candidate short-form clip windows without external AI dependencies.
"""

import math
import re
from typing import List

from app.models import HighlightCandidate, HighlightScore, TimestampedTranscript, TranscriptSegment


class HighlightScoringError(Exception):
    """Domain exception raised when highlight scoring or candidate generation fails."""

    pass


class HighlightScoringService:
    """Service responsible for deterministic transcript highlight scoring and candidate generation."""

    # Weights for overall score computation (must sum to 1.0)
    WEIGHT_HOOK = 0.30
    WEIGHT_CURIOSITY = 0.25
    WEIGHT_EMOTION = 0.20
    WEIGHT_INFO_DENSITY = 0.25

    # Heuristic pattern definitions for scoring signals
    HOOK_PATTERNS = [
        r"\bhere'?s why\b",
        r"\bthe biggest mistake\b",
        r"\byou won'?t believe\b",
        r"\bthe secret\b",
        r"\bthis changed everything\b",
        r"\bmost people don'?t know\b",
        r"\bthe truth is\b",
        r"\blisten to this\b",
        r"\bthe reason is\b",
        r"\bpay attention\b",
        r"\bwatch (this|until the end)\b",
        r"\bstop (doing|making)\b",
        r"\bnever (do|use|make)\b",
        r"\bthe #?1 (way|thing|mistake|secret)\b",
    ]

    CURIOSITY_PATTERNS = [
        r"\?",
        r"\bwhy\b",
        r"\bhow\b",
        r"\bwhat if\b",
        r"\bimagine\b",
        r"\bdid you know\b",
        r"\bthe reason\b",
        r"\bwonder\b",
        r"\bcurious\b",
        r"\bquestion\b",
        r"\bwhat happens when\b",
    ]

    EMOTION_PATTERNS = [
        r"\bamazing\b",
        r"\bcrazy\b",
        r"\bshocking\b",
        r"\bterrible\b",
        r"\blove\b",
        r"\bhate\b",
        r"\bfear\b",
        r"\bexcited\b",
        r"\bangry\b",
        r"\bsurprising\b",
        r"\bincredible\b",
        r"\bworst\b",
        r"\bbest\b",
        r"\binsane\b",
        r"\bunbelievable\b",
        r"\bdisaster\b",
        r"\bhuge\b",
        r"\bfail(ed|ure)?\b",
        r"\bwinner\b",
        r"\bdanger(ous)?\b",
    ]

    INFO_DENSITY_PATTERNS = [
        r"\b\d+(?:\.\d+)?%?\b",  # Numbers and percentages
        r"\b(increase|decrease|double|triple|grow|drop|boost|reduce)\b",
        r"\b(better|faster|cheaper|easier|worse|higher|lower)\b",
        r"\b(proven|result|strategy|technique|method|step|framework)\b",
        r"\b(first|second|third|finally)\b",
    ]

    def score_text(self, text: str) -> HighlightScore:
        """Calculate multi-dimensional normalized highlight scores for a given text string.

        Args:
            text: Transcribed text string.

        Returns:
            HighlightScore: Normalized scores (0.0 to 1.0) for hook, emotion,
                            curiosity, information density, and weighted overall.

        Raises:
            HighlightScoringError: If text is invalid or non-string.
        """
        if not isinstance(text, str):
            raise HighlightScoringError(f"Expected text string for scoring, got {type(text).__name__}")

        clean_text = text.strip()
        if not clean_text:
            return HighlightScore(
                overall=0.0,
                hook=0.0,
                emotion=0.0,
                curiosity=0.0,
                information_density=0.0,
            )

        lower_text = clean_text.lower()
        words = re.findall(r"\b\w+\b", lower_text)
        word_count = len(words)

        # 1. Hook Score Calculation
        hook_hits = sum(len(re.findall(pattern, lower_text)) for pattern in self.HOOK_PATTERNS)
        # 1 hit = 0.6, 2+ hits = 1.0 (scaled smoothly)
        hook_score = min(1.0, hook_hits * 0.5)

        # 2. Curiosity Score Calculation
        curiosity_hits = sum(len(re.findall(pattern, lower_text)) for pattern in self.CURIOSITY_PATTERNS)
        curiosity_score = min(1.0, curiosity_hits * 0.35)

        # 3. Emotion Score Calculation
        emotion_hits = sum(len(re.findall(pattern, lower_text)) for pattern in self.EMOTION_PATTERNS)
        emotion_score = min(1.0, emotion_hits * 0.35)

        # 4. Information Density Score Calculation
        info_hits = sum(len(re.findall(pattern, lower_text)) for pattern in self.INFO_DENSITY_PATTERNS)
        # Density considers number of specific data/claims relative to text volume, plus baseline word presence
        density_factor = (info_hits / max(10, word_count)) * 5.0
        word_richness = min(1.0, word_count / 30.0) * 0.4
        info_density_score = min(1.0, min(0.6, density_factor) + word_richness)

        # 5. Overall Weighted Composite Score
        overall_score = (
            (self.WEIGHT_HOOK * hook_score)
            + (self.WEIGHT_CURIOSITY * curiosity_score)
            + (self.WEIGHT_EMOTION * emotion_score)
            + (self.WEIGHT_INFO_DENSITY * info_density_score)
        )
        overall_score = min(1.0, max(0.0, overall_score))

        return HighlightScore(
            overall=float(round(overall_score, 4)),
            hook=float(round(hook_score, 4)),
            emotion=float(round(emotion_score, 4)),
            curiosity=float(round(curiosity_score, 4)),
            information_density=float(round(info_density_score, 4)),
        )

    def score_segment(self, segment: TranscriptSegment) -> HighlightScore:
        """Calculate highlight score for a single TranscriptSegment.

        Args:
            segment: A TranscriptSegment instance.

        Returns:
            HighlightScore: Calculated scores.

        Raises:
            HighlightScoringError: If segment is invalid.
        """
        if not isinstance(segment, TranscriptSegment):
            raise HighlightScoringError(
                f"Expected TranscriptSegment, got {type(segment).__name__}"
            )
        return self.score_text(segment.text)

    def generate_candidates(
        self,
        transcript: TimestampedTranscript,
        min_duration: float = 30.0,
        max_duration: float = 120.0,
        target_duration: float = 60.0,
        allow_overlap: bool = False,
    ) -> List[HighlightCandidate]:
        """Generate and rank short-form video candidate windows from transcript segments.

        Candidate timestamps strictly originate from the underlying transcript segment
        boundaries. Neighboring segments are combined to construct coherent windows
        fitting the target duration constraints.

        Args:
            transcript: TimestampedTranscript containing ordered speech segments.
            min_duration: Minimum duration of a candidate in seconds (default 30.0).
            max_duration: Maximum duration of a candidate in seconds (default 120.0).
            target_duration: Target ideal duration in seconds (default 60.0).
            allow_overlap: Whether to allow overlapping candidate time windows.

        Returns:
            List[HighlightCandidate]: Ranked candidate windows in descending order of overall score.

        Raises:
            HighlightScoringError: If duration parameters are invalid, non-finite, or inconsistent.
        """
        # Validate transcript input
        if not isinstance(transcript, TimestampedTranscript):
            raise HighlightScoringError(
                f"Expected TimestampedTranscript, got {type(transcript).__name__}"
            )

        # Validate duration parameters
        for name, val in [
            ("min_duration", min_duration),
            ("max_duration", max_duration),
            ("target_duration", target_duration),
        ]:
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise HighlightScoringError(f"{name} must be a numeric value, got {type(val).__name__}")
            if math.isnan(val) or math.isinf(val) or val <= 0:
                raise HighlightScoringError(f"{name} must be a finite positive number, got {val}")

        if min_duration > max_duration:
            raise HighlightScoringError(
                f"min_duration ({min_duration}s) cannot be greater than max_duration ({max_duration}s)"
            )
        if target_duration < min_duration or target_duration > max_duration:
            raise HighlightScoringError(
                f"target_duration ({target_duration}s) must be between min_duration ({min_duration}s) "
                f"and max_duration ({max_duration}s)"
            )

        segments = transcript.segments
        if not segments:
            return []

        total_transcript_duration = segments[-1].end_seconds - segments[0].start_seconds

        # Special case: If entire transcript is shorter than min_duration, return single candidate spanning all segments
        if total_transcript_duration < min_duration:
            combined_text = " ".join(s.text.strip() for s in segments if s.text.strip())
            if not combined_text:
                return []
            start = segments[0].start_seconds
            end = segments[-1].end_seconds
            dur = float(round(end - start, 3))
            score = self.score_text(combined_text)
            return [
                HighlightCandidate(
                    start_seconds=start,
                    end_seconds=end,
                    duration_seconds=dur,
                    text=combined_text,
                    score=score,
                )
            ]

        # Generate candidate windows combining contiguous segments
        raw_candidates: List[HighlightCandidate] = []
        n = len(segments)

        for i in range(n):
            accumulated_texts = []
            start_sec = segments[i].start_seconds

            for j in range(i, n):
                accumulated_texts.append(segments[j].text.strip())
                end_sec = segments[j].end_seconds
                duration = end_sec - start_sec

                # Exceeds max duration: cannot extend this window further
                if duration > max_duration + 1e-4:
                    break

                # Fits within [min_duration, max_duration]
                if duration >= min_duration - 1e-4:
                    text_content = " ".join(t for t in accumulated_texts if t)
                    if text_content:
                        dur_rounded = float(round(duration, 3))
                        score = self.score_text(text_content)
                        raw_candidates.append(
                            HighlightCandidate(
                                start_seconds=start_sec,
                                end_seconds=end_sec,
                                duration_seconds=dur_rounded,
                                text=text_content,
                                score=score,
                            )
                        )

        if not raw_candidates:
            # Fallback: if no single window met min_duration, take the largest valid window
            combined_text = " ".join(s.text.strip() for s in segments if s.text.strip())
            start = segments[0].start_seconds
            end = segments[-1].end_seconds
            score = self.score_text(combined_text)
            return [
                HighlightCandidate(
                    start_seconds=start,
                    end_seconds=end,
                    duration_seconds=float(round(end - start, 3)),
                    text=combined_text,
                    score=score,
                )
            ]

        # Sort all raw candidates deterministically by overall score descending,
        # using start_seconds ascending as tie-breaker.
        raw_candidates.sort(key=lambda c: (-c.score.overall, c.start_seconds, c.end_seconds))

        if allow_overlap:
            return raw_candidates

        # Deduplicate overlapping candidate windows greedily based on highest ranking score
        selected_candidates: List[HighlightCandidate] = []
        for candidate in raw_candidates:
            overlap = False
            for selected in selected_candidates:
                # Check for temporal overlap between candidate and already selected candidate
                if not (candidate.end_seconds <= selected.start_seconds + 1e-4 or candidate.start_seconds >= selected.end_seconds - 1e-4):
                    overlap = True
                    break
            if not overlap:
                selected_candidates.append(candidate)

        return selected_candidates
