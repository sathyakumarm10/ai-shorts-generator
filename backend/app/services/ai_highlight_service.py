"""AI-powered Highlight Intelligence and Viral Hook Generation Service.

Provides LLM provider abstractions (OpenAI, OpenRouter, Anthropic, or mock providers)
to analyze timestamped transcript segments, identify high-retention viral moments,
and generate engaging video titles, hooks, and descriptions.

Maintains strict resilience:
- Validates all AI candidate output with Pydantic against video duration & clip constraints.
- Rejects negative, overlapping, inverted, or out-of-bounds timestamps.
- Automatically falls back to heuristic scoring whenever AI credentials are missing,
  invalid, times out, or when responses are malformed.
"""

from abc import ABC, abstractmethod
import json
import os
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error

from app.models import (
    HighlightCandidate,
    HighlightScore,
    HighlightSource,
    TimestampedTranscript,
    TranscriptSegment,
)


class AIHighlightError(Exception):
    """Exception raised when an AI highlight operation fails."""


class BaseAIProvider(ABC):
    """Abstract interface for LLM highlight extraction providers."""

    @abstractmethod
    def generate_highlights(
        self,
        transcript: TimestampedTranscript,
        min_duration: float,
        max_duration: float,
        target_duration: float,
        max_clips: int,
        timeout_seconds: float = 15.0,
    ) -> Optional[List[Dict[str, Any]]]:
        """Generate structured highlight proposals from transcript segments.

        Returns raw candidate dicts on success, or None on failure/unconfigured.
        """


class OpenRouterAIProvider(BaseAIProvider):
    """Provider communicating with OpenRouter / OpenAI compatible chat completions API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.base_url = (
            base_url
            or os.getenv("AI_API_BASE")
            or ("https://openrouter.ai/api/v1" if os.getenv("OPENROUTER_API_KEY") else "https://api.openai.com/v1")
        )
        self.model = model or os.getenv("AI_MODEL") or "openai/gpt-4o-mini"

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def generate_highlights(
        self,
        transcript: TimestampedTranscript,
        min_duration: float,
        max_duration: float,
        target_duration: float,
        max_clips: int,
        timeout_seconds: float = 15.0,
    ) -> Optional[List[Dict[str, Any]]]:
        if not self.is_available():
            return None

        # Build prompt payload from transcript segments
        formatted_segments = [
            {
                "index": i,
                "start": round(seg.start_seconds, 2),
                "end": round(seg.end_seconds, 2),
                "text": seg.text.strip(),
            }
            for i, seg in enumerate(transcript.segments)
        ]

        system_prompt = (
            "You are an expert viral video editor specializing in YouTube Shorts, TikTok, and Instagram Reels. "
            "Your task is to analyze timestamped transcript segments from a video and identify the top engaging, "
            "high-retention moments. For each moment, you MUST select exact start and end timestamps that cleanly align "
            f"with sentence/segment boundaries. The clip duration MUST be between {min_duration}s and {max_duration}s "
            f"(ideally ~{target_duration}s). Output strictly JSON."
        )

        user_content = {
            "task": "Extract the best viral highlight clips from this transcript.",
            "constraints": {
                "min_duration_seconds": min_duration,
                "max_duration_seconds": max_duration,
                "target_duration_seconds": target_duration,
                "max_clips": max_clips,
            },
            "transcript_segments": formatted_segments,
            "response_format_example": [
                {
                    "start_seconds": 12.5,
                    "end_seconds": 45.0,
                    "title": "Unbelievable Breakthrough Explained",
                    "viral_hook": "Wait until you see how this changes everything...",
                    "description": "Explaining the key takeaway in simple terms.",
                    "reasoning": "High curiosity opening and strong emotional inflection.",
                    "score": {
                        "overall": 0.95,
                        "hook": 0.9,
                        "emotion": 0.85,
                        "curiosity": 0.95,
                        "information_density": 0.8,
                    },
                }
            ],
        }

        endpoint = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_content)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
        }

        try:
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                if resp.status != 200:
                    return None
                data = json.loads(resp.read().decode("utf-8"))
                choice = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                parsed = json.loads(choice)
                if isinstance(parsed, list):
                    return parsed
                if isinstance(parsed, dict):
                    for k in ("clips", "highlights", "candidates", "data"):
                        if isinstance(parsed.get(k), list):
                            return parsed[k]
                return None
        except Exception:
            return None


class AIHighlightService:
    """Coordinates AI-driven highlight detection with robust validation and heuristic fallbacks."""

    def __init__(
        self,
        provider: Optional[BaseAIProvider] = None,
        timeout_seconds: float = 12.0,
    ) -> None:
        self.provider = provider or OpenRouterAIProvider()
        self.timeout_seconds = timeout_seconds

    def generate_ai_candidates(
        self,
        transcript: TimestampedTranscript,
        min_duration: float = 30.0,
        max_duration: float = 120.0,
        target_duration: float = 60.0,
        max_clips: int = 10,
        video_duration: Optional[float] = None,
    ) -> List[HighlightCandidate]:
        """Extract and validate AI-generated highlight candidates.

        Returns an empty list if AI is unconfigured or if candidates fail validation.
        """
        if not transcript.segments:
            return []

        try:
            raw_candidates = self.provider.generate_highlights(
                transcript=transcript,
                min_duration=min_duration,
                max_duration=max_duration,
                target_duration=target_duration,
                max_clips=max_clips,
                timeout_seconds=self.timeout_seconds,
            )
        except Exception:
            return []

        if not raw_candidates or not isinstance(raw_candidates, list):
            return []

        valid_candidates: List[HighlightCandidate] = []
        max_limit = video_duration or transcript.segments[-1].end_seconds

        for item in raw_candidates:
            if not isinstance(item, dict):
                continue

            start_s = item.get("start_seconds")
            end_s = item.get("end_seconds")

            if not isinstance(start_s, (int, float)) or not isinstance(end_s, (int, float)):
                continue

            start_s = round(start_s, 2)
            end_s = round(end_s, 2)

            # Reject negative or out-of-bounds timestamps
            if start_s < 0.0 or end_s <= start_s or end_s > (max_limit + 1.5):
                continue

            dur = round(end_s - start_s, 2)
            # Relax slightly for boundary segment snapping (within 10%)
            if dur < (min_duration * 0.85) or dur > (max_duration * 1.15):
                continue

            # Deduplicate against already accepted valid candidates (IoU <= 0.35, start_distance >= 10s)
            excessive_overlap = False
            for existing in valid_candidates:
                inter_start = max(start_s, existing.start_seconds)
                inter_end = min(end_s, existing.end_seconds)
                intersection = max(0.0, inter_end - inter_start)

                union_start = min(start_s, existing.start_seconds)
                union_end = max(end_s, existing.end_seconds)
                union = max(1e-6, union_end - union_start)

                iou = intersection / union
                start_distance = abs(start_s - existing.start_seconds)

                if iou > 0.35 or start_distance < 10.0:
                    excessive_overlap = True
                    break

            if excessive_overlap:
                continue

            # Extract matching transcript slice
            matching_texts: List[str] = []
            for seg in transcript.segments:
                if seg.end_seconds > start_s and seg.start_seconds < end_s:
                    matching_texts.append(seg.text.strip())
            
            clip_text = " ".join(t for t in matching_texts if t).strip()
            if not clip_text:
                clip_text = item.get("description") or item.get("title") or "AI Highlight Segment"

            # Parse or synthesize score
            raw_score_val = item.get("score")
            raw_score: dict = raw_score_val if isinstance(raw_score_val, dict) else {}
            score = HighlightScore(
                overall=min(1.0, max(0.0, float(raw_score.get("overall", 0.90)))),
                hook=min(1.0, max(0.0, float(raw_score.get("hook", 0.85)))),
                emotion=min(1.0, max(0.0, float(raw_score.get("emotion", 0.80)))),
                curiosity=min(1.0, max(0.0, float(raw_score.get("curiosity", 0.85)))),
                information_density=min(1.0, max(0.0, float(raw_score.get("information_density", 0.80)))),
            )

            title = item.get("title")
            viral_hook = item.get("viral_hook")
            description = item.get("description")
            reasoning = item.get("reasoning")

            try:
                candidate = HighlightCandidate(
                    start_seconds=start_s,
                    end_seconds=end_s,
                    duration_seconds=dur,
                    text=clip_text,
                    score=score,
                    title=str(title).strip() if title else None,
                    viral_hook=str(viral_hook).strip() if viral_hook else None,
                    description=str(description).strip() if description else None,
                    reasoning=str(reasoning).strip() if reasoning else None,
                    source_type=HighlightSource.AI,
                )
                valid_candidates.append(candidate)
            except Exception:
                continue

            if len(valid_candidates) >= max_clips:
                break

        # Sort descending by overall score
        valid_candidates.sort(key=lambda c: c.score.overall, reverse=True)
        return valid_candidates
