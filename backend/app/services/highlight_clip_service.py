"""Highlight candidate to video clip generation service.

This module provides the `HighlightClipService` for converting ranked
`HighlightCandidate` segments into rendered MP4 video clips by delegating to
the existing `VideoClipService`.
"""

import math
from pathlib import Path
from typing import List, Optional

from app.models import GeneratedHighlightClip, HighlightCandidate, IngestedVideo, VideoClipRequest
from app.services.video_clip_service import VideoClipError, VideoClipService


class HighlightClipError(Exception):
    """Domain exception raised when rendering clips from highlight candidates fails."""

    pass


class HighlightClipService:
    """Service responsible for converting highlight candidates into rendered video clips."""

    def __init__(self, video_clip_service: Optional[VideoClipService] = None) -> None:
        self.video_clip_service = video_clip_service or VideoClipService()

    def generate_clips(
        self,
        video: IngestedVideo | str | Path,
        candidates: List[HighlightCandidate],
        max_clips: int = 10,
    ) -> List[GeneratedHighlightClip]:
        """Generate rendered MP4 video clips for the top ranked highlight candidates.

        Args:
            video: IngestedVideo instance or path to the source video file.
            candidates: Ranked list of HighlightCandidate objects.
            max_clips: Maximum number of candidate clips to render (>= 1).

        Returns:
            List[GeneratedHighlightClip]: List of generated clips with candidate metadata and output file paths.

        Raises:
            HighlightClipError: If source video is missing, max_clips is invalid,
                               candidates are malformed, or video clipping fails.
        """
        # Resolve and validate source video path
        if isinstance(video, IngestedVideo):
            source_path = Path(video.file_path)
        elif isinstance(video, (str, Path)):
            source_path = Path(video)
        else:
            raise HighlightClipError(f"Invalid video type: expected IngestedVideo, str, or Path, got {type(video).__name__}")

        if not source_path.is_file():
            raise HighlightClipError(f"Source video file not found: {source_path}")

        # Validate max_clips parameter
        if isinstance(max_clips, bool) or not isinstance(max_clips, (int, float)):
            raise HighlightClipError(f"max_clips must be a numeric integer, got {type(max_clips).__name__}")

        if isinstance(max_clips, float):
            if not max_clips.is_integer() or math.isnan(max_clips) or math.isinf(max_clips):
                raise HighlightClipError(f"max_clips must be a positive integer, got {max_clips}")
            max_clips_int = int(max_clips)
        else:
            max_clips_int = max_clips

        if max_clips_int < 1:
            raise HighlightClipError(f"max_clips must be at least 1, got {max_clips_int}")

        # Validate candidates list
        if not isinstance(candidates, list):
            raise HighlightClipError(f"candidates must be a list, got {type(candidates).__name__}")

        for idx, cand in enumerate(candidates):
            if not isinstance(cand, HighlightCandidate):
                raise HighlightClipError(
                    f"Candidate at index {idx} is not a HighlightCandidate instance (got {type(cand).__name__})"
                )

        if not candidates:
            return []

        selected_candidates = candidates[:max_clips_int]
        generated_clips: List[GeneratedHighlightClip] = []
        failure_messages: List[str] = []

        failures = 0
        for clip_idx, candidate in enumerate(selected_candidates, start=1):
            # Construct VideoClipRequest without modifying candidate values
            try:
                clip_request = VideoClipRequest(
                    start_seconds=candidate.start_seconds,
                    duration_seconds=candidate.duration_seconds,
                )
            except Exception:
                failures += 1
                failure_messages.append("Failed to construct a clip request.")
                continue

            # Render clip via existing VideoClipService with index-based naming
            try:
                custom_filename = f"clip_{clip_idx:03d}.mp4"
                ingested_clip = self.video_clip_service.create_clip(video, clip_request, output_filename=custom_filename)
            except VideoClipError:
                failures += 1
                failure_messages.append("Video clip generation failed for candidate.")
                continue
            except Exception:
                failures += 1
                failure_messages.append("Unexpected error during video clipping.")
                continue

            # Verify rendered output file
            output_file = Path(ingested_clip.file_path)
            if not output_file.is_file():
                failures += 1
                failure_messages.append("Generated clip file does not exist on disk.")
                continue

            try:
                file_size = output_file.stat().st_size
                if file_size <= 0:
                    failures += 1
                    failure_messages.append("Generated clip file is empty.")
                    continue
            except OSError:
                failures += 1
                failure_messages.append("Generated clip file could not be inspected.")
                continue

            generated_clips.append(
                GeneratedHighlightClip(
                    candidate=candidate,
                    file_path=str(output_file),
                )
            )

        if failures and not generated_clips:
            raise HighlightClipError(failure_messages[0] if failure_messages else "All candidate clip renders failed.")

        return generated_clips
