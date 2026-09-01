"""End-to-End automatic Shorts generation orchestration service.

This module provides the central `ShortsGenerationService` that coordinates
ingestion, metadata extraction, speech-to-text transcription, highlight detection,
candidate clipping, vertical 9:16 framing, and styled caption burn-in into a single
unified video processing pipeline.
"""

from typing import Callable, List, Optional

from app.models import (
    CaptionSegment,
    CaptionTrack,
    FramingType,
    GeneratedShort,
    HighlightCandidate,
    HighlightSource,
    JobStatus,
    ShortsGenerationRequest,
    ShortsGenerationResult,
    VerticalVideoRequest,
    VideoSource,
)
from app.services.ai_highlight_service import AIHighlightService
from app.services.caption_burn_service import CaptionBurnError, CaptionBurnService
from app.services.caption_service import CaptionService, CaptionServiceError
from app.services.highlight_clip_service import HighlightClipError, HighlightClipService
from app.services.highlight_scoring_service import HighlightScoringError, HighlightScoringService
from app.services.transcription_service import FasterWhisperTranscriptionProvider, TranscriptionError, TranscriptionService
from app.services.vertical_video_service import VerticalVideoError, VerticalVideoService
from app.services.video_ingestion_service import VideoIngestionError, VideoIngestionService
from app.services.video_metadata_service import VideoMetadataError, VideoMetadataService


class ShortsGenerationError(Exception):
    """Domain exception raised when end-to-end Shorts generation fails."""

    pass


class ShortsGenerationService:
    """Orchestrates the entire video-to-Shorts generation pipeline."""

    def __init__(
        self,
        ingestion_service: Optional[VideoIngestionService] = None,
        metadata_service: Optional[VideoMetadataService] = None,
        transcription_service: Optional[TranscriptionService] = None,
        highlight_scoring_service: Optional[HighlightScoringService] = None,
        highlight_clip_service: Optional[HighlightClipService] = None,
        vertical_video_service: Optional[VerticalVideoService] = None,
        caption_service: Optional[CaptionService] = None,
        caption_burn_service: Optional[CaptionBurnService] = None,
        ai_highlight_service: Optional[AIHighlightService] = None,
    ) -> None:
        self.ingestion_service = ingestion_service or VideoIngestionService()
        self.metadata_service = metadata_service or VideoMetadataService()
        self.transcription_service = transcription_service or TranscriptionService(
            provider=FasterWhisperTranscriptionProvider()
        )
        self.highlight_scoring_service = highlight_scoring_service or HighlightScoringService()
        self.highlight_clip_service = highlight_clip_service or HighlightClipService()
        self.vertical_video_service = vertical_video_service or VerticalVideoService()
        self.caption_service = caption_service or CaptionService()
        self.caption_burn_service = caption_burn_service or CaptionBurnService(
            caption_service=self.caption_service
        )
        self.ai_highlight_service = ai_highlight_service or AIHighlightService()

    def generate(
        self,
        source: VideoSource | ShortsGenerationRequest,
        clip_duration_seconds: float = 60.0,
        number_of_clips: int = 3,
        include_captions: bool = True,
        min_clip_duration: float = 30.0,
        max_clip_duration: float = 120.0,
        vertical_width: int = 1080,
        vertical_height: int = 1920,
        progress_callback: Optional[Callable[[JobStatus, float, str], None]] = None,
    ) -> ShortsGenerationResult:
        """Run the full end-to-end shorts generation pipeline.

        Pipeline Stages:
            1. Ingest source video (local file or download).
            2. Extract video metadata (resolution, duration, codecs).
            3. Transcribe audio into timestamped speech segments.
            4. Detect and rank highlight candidates from the transcript.
            5. Render trimmed MP4 clips for the highest-ranked candidates.
            6. Convert each clip to 9:16 vertical video without geometric distortion.
            7. (Optional) Slice and offset transcript captions, burning them into vertical video.
            8. Assemble and return final ShortsGenerationResult.

        Args:
            source: VideoSource or validated ShortsGenerationRequest.
            clip_duration_seconds: Desired target duration of each short.
            number_of_clips: Number of top highlight candidates to render.
            include_captions: Whether to burn styled captions into the video.
            min_clip_duration: Minimum allowed duration for a candidate.
            max_clip_duration: Maximum allowed duration for a candidate.
            vertical_width: Target vertical width in pixels.
            vertical_height: Target vertical height in pixels.
            progress_callback: Optional callback receiving (status, progress_percent, message).

        Returns:
            ShortsGenerationResult: Complete result with ingested video, metadata,
                                    transcript, candidate list, and rendered shorts.

        Raises:
            ShortsGenerationError: If any stage in the pipeline fails.
        """
        def report_progress(status: JobStatus, percent: float, msg: str) -> None:
            if progress_callback is not None:
                try:
                    progress_callback(status, percent, msg)
                except Exception:
                    pass

        # Validate or build ShortsGenerationRequest
        if isinstance(source, ShortsGenerationRequest):
            req = source
        elif isinstance(source, VideoSource):
            try:
                req = ShortsGenerationRequest(
                    source=source,
                    clip_duration_seconds=clip_duration_seconds,
                    number_of_clips=number_of_clips,
                    include_captions=include_captions,
                    min_clip_duration=min_clip_duration,
                    max_clip_duration=max_clip_duration,
                    vertical_width=vertical_width,
                    vertical_height=vertical_height,
                )
            except Exception as exc:
                raise ShortsGenerationError(f"Invalid ShortsGenerationRequest parameters: {exc}") from exc
        else:
            raise ShortsGenerationError(
                f"Expected VideoSource or ShortsGenerationRequest, got {type(source).__name__}"
            )

        # 1. Ingest source video
        report_progress(JobStatus.INGESTING, 10.0, "Ingesting source video")
        try:
            ingested_video = self.ingestion_service.ingest(req.source)
        except (VideoIngestionError, Exception) as exc:
            raise ShortsGenerationError(f"Video ingestion failed: {exc}") from exc

        # 2. Extract metadata
        report_progress(JobStatus.EXTRACTING_METADATA, 20.0, "Extracting video metadata")
        try:
            metadata = self.metadata_service.extract_metadata(ingested_video.file_path)
        except (VideoMetadataError, Exception) as exc:
            raise ShortsGenerationError(f"Video metadata extraction failed: {exc}") from exc

        # 3. Transcribe audio into timestamped transcript
        report_progress(JobStatus.TRANSCRIBING, 35.0, "Transcribing audio to text")
        try:
            transcript = self.transcription_service.transcribe(ingested_video)
        except (TranscriptionError, Exception) as exc:
            raise ShortsGenerationError(f"Audio transcription failed: {exc}") from exc

        # 4. Highlight detection and candidate generation
        report_progress(JobStatus.FINDING_HIGHLIGHTS, 50.0, "Analyzing transcript for highlights")
        candidates: List[HighlightCandidate] = []

        # Try AI intelligent candidate extraction first
        try:
            ai_candidates = self.ai_highlight_service.generate_ai_candidates(
                transcript=transcript,
                min_duration=req.min_clip_duration,
                max_duration=req.max_clip_duration,
                target_duration=req.clip_duration_seconds,
                max_clips=req.number_of_clips,
                video_duration=metadata.duration_seconds,
            )
            if ai_candidates:
                candidates = ai_candidates
        except Exception:
            candidates = []

        # Fallback to deterministic heuristic scoring if AI yielded no valid candidates
        if not candidates:
            try:
                heuristic_candidates: List[HighlightCandidate] = self.highlight_scoring_service.generate_candidates(
                    transcript,
                    min_duration=req.min_clip_duration,
                    max_duration=req.max_clip_duration,
                    target_duration=req.clip_duration_seconds,
                    allow_overlap=False,
                )
                # Synthesize informative titles and viral hooks for heuristic candidates
                for i, c in enumerate(heuristic_candidates, start=1):
                    preview = (c.text[:45] + "...") if len(c.text) > 45 else c.text
                    c.title = f"Highlight #{i}: {preview}"
                    c.viral_hook = f"Must Watch: {c.text[:55]}..."
                    c.description = c.text
                    c.source_type = HighlightSource.HEURISTIC
                candidates = heuristic_candidates
            except (HighlightScoringError, Exception) as exc:
                raise ShortsGenerationError(f"Highlight candidate generation failed: {exc}") from exc

        if not candidates:
            report_progress(JobStatus.FINDING_HIGHLIGHTS, 60.0, "No candidate clips found in transcript")
            return ShortsGenerationResult(
                source_video=ingested_video,
                metadata=metadata,
                transcript=transcript,
                candidates=[],
                generated_shorts=[],
            )

        # 5. Render candidate raw clips
        report_progress(JobStatus.GENERATING_CLIPS, 65.0, f"Rendering {min(len(candidates), req.number_of_clips)} candidate clips")
        try:
            rendered_clips = self.highlight_clip_service.generate_clips(
                video=ingested_video,
                candidates=candidates,
                max_clips=req.number_of_clips,
            )
        except (HighlightClipError, Exception) as exc:
            raise ShortsGenerationError(f"Highlight clip rendering failed: {exc}") from exc

        # 6 & 7. Convert each rendered clip to vertical 9:16 and optionally burn relative captions
        generated_shorts: List[GeneratedShort] = []
        for idx, clip in enumerate(rendered_clips, start=1):
            cand = clip.candidate

            # Convert to vertical 9:16
            report_progress(JobStatus.CONVERTING_VERTICAL, 80.0, f"Converting short #{idx} to 9:16 vertical format (smart framing)")
            try:
                vert_req = VerticalVideoRequest(width=req.vertical_width, height=req.vertical_height)
                vertical_video = self.vertical_video_service.convert_to_vertical(clip.file_path, vert_req)
            except (VerticalVideoError, Exception) as exc:
                raise ShortsGenerationError(
                    f"Vertical 9:16 conversion failed for short #{idx} ({cand.start_seconds}s-{cand.end_seconds}s): {exc}"
                ) from exc

            framing_type = vertical_video.framing_type or FramingType.CENTER_CROP
            captioned_clip_path: Optional[str] = None
            final_path = vertical_video.file_path

            # Optional: Extract relative captions for this clip's time window and burn them
            if req.include_captions:
                report_progress(JobStatus.ADDING_CAPTIONS, 90.0, f"Burning styled captions into short #{idx}")
                relative_segments: List[CaptionSegment] = []
                c_start = cand.start_seconds
                c_end = cand.end_seconds

                for seg in transcript.segments:
                    # Check if transcript segment overlaps candidate window
                    if seg.end_seconds > c_start and seg.start_seconds < c_end:
                        # Shift timestamp to local clip time coordinate [0.0, duration]
                        rel_start = max(0.0, round(seg.start_seconds - c_start, 3))
                        rel_end = min(cand.duration_seconds, round(seg.end_seconds - c_start, 3))
                        clean_text = seg.text.strip()
                        if rel_end > rel_start and clean_text:
                            relative_segments.append(
                                CaptionSegment(
                                    start_seconds=rel_start,
                                    end_seconds=rel_end,
                                    text=clean_text,
                                )
                            )

                try:
                    caption_track = CaptionTrack(segments=relative_segments)
                    captioned_video = self.caption_burn_service.burn_captions(
                        vertical_video.file_path,
                        caption_track,
                        preset=req.caption_preset,
                        enable_karaoke=getattr(req, "enable_karaoke", True),
                        karaoke_active_color=getattr(req, "karaoke_active_color", None),
                    )
                    captioned_clip_path = captioned_video.file_path
                    final_path = captioned_video.file_path
                except (CaptionServiceError, CaptionBurnError, Exception) as exc:
                    # Gracefully fall back to non-captioned vertical video so job completes
                    captioned_clip_path = None
                    final_path = vertical_video.file_path

            generated_shorts.append(
                GeneratedShort(
                    index=idx,
                    candidate=cand,
                    source_clip_path=clip.file_path,
                    vertical_clip_path=vertical_video.file_path,
                    captioned_clip_path=captioned_clip_path,
                    final_file_path=final_path,
                    framing_type=framing_type,
                    caption_preset=req.caption_preset if captioned_clip_path else None,
                    is_karaoke=bool(captioned_clip_path and getattr(req, "enable_karaoke", True)),
                )
            )

        report_progress(JobStatus.ADDING_CAPTIONS, 95.0, f"Finalizing {len(generated_shorts)} shorts")
        return ShortsGenerationResult(
            source_video=ingested_video,
            metadata=metadata,
            transcript=transcript,
            candidates=candidates,
            generated_shorts=generated_shorts,
        )
