"""Deterministic clip planning service.

This module provides the `ClipPlannerService` for generating candidate clip
segments from video metadata based on duration constraints and non-overlapping
even distribution across the video timeline.
"""

import math
from typing import List

from app.models import PlannedClip, VideoMetadata


class ClipPlanningError(Exception):
    """Domain exception raised when clip planning fails or inputs are invalid."""

    pass


class ClipPlannerService:
    """Service responsible for planning non-overlapping video clips deterministically."""

    def plan_clips(
        self,
        metadata: VideoMetadata,
        clip_duration_seconds: float,
        number_of_clips: int,
    ) -> List[PlannedClip]:
        """Plan candidate non-overlapping clip segments evenly distributed across the video.

        Args:
            metadata: VideoMetadata containing duration_seconds of the source video.
            clip_duration_seconds: Desired duration of each clip in seconds (30-120).
            number_of_clips: Number of clips to generate (>= 1).

        Returns:
            List[PlannedClip]: List of planned clip segments with start and end timestamps.

        Raises:
            ClipPlanningError: If inputs are invalid, out of range, non-finite,
                               or if the source video duration cannot fit the requested clips.
        """
        # Validate metadata parameter
        if not isinstance(metadata, VideoMetadata):
            raise ClipPlanningError(
                f"Invalid metadata type: expected VideoMetadata, got {type(metadata).__name__}"
            )

        video_duration = metadata.duration_seconds
        if isinstance(video_duration, bool) or not isinstance(video_duration, (int, float)):
            raise ClipPlanningError(
                f"Source video duration must be a numeric value, got {type(video_duration).__name__}"
            )

        if math.isnan(video_duration) or math.isinf(video_duration) or video_duration <= 0:
            raise ClipPlanningError(
                f"Source video duration must be a finite positive number, got: {video_duration}"
            )

        # Validate clip_duration_seconds parameter
        if isinstance(clip_duration_seconds, bool) or not isinstance(clip_duration_seconds, (int, float)):
            raise ClipPlanningError(
                f"clip_duration_seconds must be a numeric value, got: {type(clip_duration_seconds).__name__}"
            )

        if math.isnan(clip_duration_seconds) or math.isinf(clip_duration_seconds):
            raise ClipPlanningError("clip_duration_seconds must be a finite number (got NaN or Infinity)")

        clip_duration = float(clip_duration_seconds)
        if clip_duration < 30.0 or clip_duration > 120.0:
            raise ClipPlanningError(
                f"clip_duration_seconds must be between 30 and 120 seconds, got: {clip_duration}"
            )

        # Validate number_of_clips parameter
        if isinstance(number_of_clips, bool) or not isinstance(number_of_clips, (int, float)):
            raise ClipPlanningError(
                f"number_of_clips must be an integer, got: {type(number_of_clips).__name__}"
            )

        if isinstance(number_of_clips, float):
            if math.isnan(number_of_clips) or math.isinf(number_of_clips) or not number_of_clips.is_integer():
                raise ClipPlanningError(
                    f"number_of_clips must be a finite positive integer, got: {number_of_clips}"
                )
            num_clips = int(number_of_clips)
        else:
            num_clips = number_of_clips

        if num_clips < 1:
            raise ClipPlanningError(
                f"number_of_clips must be at least 1, got: {num_clips}"
            )

        # Ensure total requested clip duration fits inside the source video
        total_required_duration = num_clips * clip_duration
        if total_required_duration > video_duration:
            raise ClipPlanningError(
                f"Source video duration ({video_duration}s) is insufficient to fit {num_clips} "
                f"non-overlapping clip(s) of {clip_duration}s (requires at least {total_required_duration}s)."
            )

        # Generate evenly distributed candidate clips
        clips: List[PlannedClip] = []

        if num_clips == 1:
            # Single clip: placed at the start of the video (0s)
            start = 0.0
            end = float(round(start + clip_duration, 6))
            clips.append(
                PlannedClip(
                    index=1,
                    start_seconds=start,
                    duration_seconds=clip_duration,
                    end_seconds=end,
                )
            )
        else:
            # Multiple clips: distribute starts across [0, video_duration - clip_duration]
            step = (video_duration - clip_duration) / (num_clips - 1)
            for i in range(num_clips):
                start = float(round(i * step, 6))
                end = float(round(start + clip_duration, 6))

                # Ensure clip does not extend beyond source duration
                if end > video_duration + 1e-6:
                    raise ClipPlanningError(
                        f"Generated clip {i+1} extends beyond source duration ({end}s > {video_duration}s)."
                    )

                clips.append(
                    PlannedClip(
                        index=i + 1,
                        start_seconds=start,
                        duration_seconds=clip_duration,
                        end_seconds=end,
                    )
                )

        # Verify non-overlapping condition
        for i in range(len(clips) - 1):
            if clips[i].end_seconds > clips[i + 1].start_seconds + 1e-6:
                raise ClipPlanningError(
                    f"Generated overlapping clips: clip {clips[i].index} ends at {clips[i].end_seconds}s "
                    f"but clip {clips[i+1].index} starts at {clips[i+1].start_seconds}s."
                )

        return clips
