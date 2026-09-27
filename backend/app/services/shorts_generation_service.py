"""End-to-end Shorts generation with explicit stage and clip outcomes."""

import logging
from typing import Callable, List, Optional

from app.models import (
    CaptionTrack,
    ClipProcessingOutcome,
    FramingType,
    GeneratedShort,
    HighlightCandidate,
    HighlightMethod,
    HighlightSource,
    JobStatus,
    OutcomeStatus,
    ProcessingStage,
    ShortsGenerationRequest,
    ShortsGenerationResult,
    StageOutcome,
    VerticalVideoRequest,
    VideoSource,
)
from app.services.ai_highlight_service import AIHighlightService
from app.services.caption_burn_service import CaptionBurnService
from app.services.caption_service import CaptionService
from app.services.highlight_clip_service import HighlightClipService
from app.services.highlight_scoring_service import HighlightScoringService
from app.services.media_output_validation_service import MediaOutputValidationService
from app.services.transcription_service import FasterWhisperTranscriptionProvider, TranscriptionService
from app.services.vertical_video_service import VerticalVideoService
from app.services.video_ingestion_service import VideoIngestionService
from app.services.video_metadata_service import VideoMetadataService

logger = logging.getLogger(__name__)


class ShortsGenerationError(Exception):
    """Pipeline error carrying separate safe and diagnostic messages."""

    def __init__(
        self,
        user_message: str,
        *,
        diagnostic: Optional[str] = None,
        stage: Optional[ProcessingStage] = None,
    ) -> None:
        self.user_message = user_message
        self.diagnostic = diagnostic or user_message
        self.stage = stage
        super().__init__(self.user_message)


class ShortsGenerationService:
    """Orchestrates ingestion, selection, rendering, validation, and captions."""

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
        output_validation_service: Optional[MediaOutputValidationService] = None,
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
        self.output_validation_service = output_validation_service or MediaOutputValidationService()

    @staticmethod
    def _failure(message: str, stage: ProcessingStage, exc: Exception) -> ShortsGenerationError:
        return ShortsGenerationError(message, diagnostic=str(exc), stage=stage)

    def generate(
        self,
        source: VideoSource | ShortsGenerationRequest,
        clip_duration_seconds: float = 60.0,
        number_of_clips: int = 10,
        include_captions: bool = True,
        min_clip_duration: float = 30.0,
        max_clip_duration: float = 120.0,
        vertical_width: int = 1080,
        vertical_height: int = 1920,
        progress_callback: Optional[Callable[[JobStatus, float, str], None]] = None,
    ) -> ShortsGenerationResult:
        def progress(status: JobStatus, percent: float, message: str) -> None:
            if progress_callback:
                progress_callback(status, percent, message)

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
                raise ShortsGenerationError("Invalid generation settings.", diagnostic=str(exc)) from exc
        else:
            raise ShortsGenerationError("Invalid video source.")

        outcomes: list[StageOutcome] = []
        warnings: list[str] = []

        progress(JobStatus.INGESTING, 10, "Ingesting source video")
        try:
            ingested_video = self.ingestion_service.ingest(req.source)
            outcomes.append(StageOutcome(stage=ProcessingStage.SOURCE_INGESTION, status=OutcomeStatus.SUCCESS, message="Source video was ingested."))
        except Exception as exc:
            raise self._failure("Source ingestion failed.", ProcessingStage.SOURCE_INGESTION, exc) from exc

        progress(JobStatus.EXTRACTING_METADATA, 20, "Extracting video metadata")
        try:
            metadata = self.metadata_service.extract_metadata(ingested_video.file_path)
            outcomes.append(StageOutcome(stage=ProcessingStage.METADATA, status=OutcomeStatus.SUCCESS, message="Video metadata was read."))
        except Exception as exc:
            raise self._failure("Video metadata could not be read.", ProcessingStage.METADATA, exc) from exc

        progress(JobStatus.TRANSCRIBING, 35, "Transcribing audio to text")
        try:
            transcript = self.transcription_service.transcribe(ingested_video)
            if not transcript.segments or not any(segment.text.strip() for segment in transcript.segments):
                raise ValueError("Transcription returned no speech segments")
            outcomes.append(StageOutcome(stage=ProcessingStage.TRANSCRIPTION, status=OutcomeStatus.SUCCESS, message="Audio transcription completed."))
        except Exception as exc:
            raise self._failure("No usable speech could be transcribed from this video.", ProcessingStage.TRANSCRIPTION, exc) from exc

        progress(JobStatus.FINDING_HIGHLIGHTS, 50, "Analyzing transcript for highlights")
        candidates: List[HighlightCandidate] = []
        highlight_method = HighlightMethod.REMOTE_AI
        try:
            candidates = self.ai_highlight_service.generate_ai_candidates(
                transcript=transcript,
                min_duration=req.min_clip_duration,
                max_duration=req.max_clip_duration,
                target_duration=req.clip_duration_seconds,
                max_clips=req.number_of_clips,
                video_duration=metadata.duration_seconds,
            )
        except Exception as exc:
            logger.warning("Remote highlight selection failed; using heuristic fallback (%s)", type(exc).__name__)

        if not candidates:
            highlight_method = HighlightMethod.HEURISTIC_FALLBACK
            fallback_warning = "Remote AI highlight selection was unavailable; heuristic selection was used."
            try:
                candidates = self.highlight_scoring_service.generate_candidates(
                    transcript,
                    min_duration=req.min_clip_duration,
                    max_duration=req.max_clip_duration,
                    target_duration=req.clip_duration_seconds,
                    allow_overlap=False,
                )
                for index, candidate in enumerate(candidates, start=1):
                    preview = candidate.text[:45] + ("..." if len(candidate.text) > 45 else "")
                    candidate.title = f"Highlight #{index}: {preview}"
                    candidate.viral_hook = f"Must Watch: {candidate.text[:55]}..."
                    candidate.description = candidate.text
                    candidate.source_type = HighlightSource.HEURISTIC
                if not candidates:
                    raise ValueError("Heuristic selection returned no candidates")
            except Exception as exc:
                raise self._failure("No highlight clips could be selected.", ProcessingStage.HIGHLIGHT_SELECTION, exc) from exc
            warnings.append(fallback_warning)
            outcomes.append(StageOutcome(stage=ProcessingStage.HIGHLIGHT_SELECTION, status=OutcomeStatus.WARNING, message=fallback_warning))
        else:
            outcomes.append(StageOutcome(stage=ProcessingStage.HIGHLIGHT_SELECTION, status=OutcomeStatus.SUCCESS, message="Highlights were selected using remote AI."))

        candidates = candidates[:req.number_of_clips]
        progress(JobStatus.GENERATING_CLIPS, 60, f"Rendering {len(candidates)} candidate clips")
        try:
            rendered_clips = self.highlight_clip_service.generate_clips(ingested_video, candidates, req.number_of_clips)
        except Exception as exc:
            raise self._failure("All highlight clip renders failed.", ProcessingStage.CLIP_RENDER, exc) from exc

        rendered_by_candidate = {
            (clip.candidate.start_seconds, clip.candidate.end_seconds): clip for clip in rendered_clips
        }
        clip_outcomes: list[ClipProcessingOutcome] = []
        generated_shorts: list[GeneratedShort] = []
        clip_render_failures = len(candidates) - len(rendered_clips)
        framing_fallbacks = 0

        for candidate_index, candidate in enumerate(candidates, start=1):
            clip = rendered_by_candidate.get((candidate.start_seconds, candidate.end_seconds))
            if clip is None:
                clip_outcomes.append(ClipProcessingOutcome(index=candidate_index, candidate=candidate, status=OutcomeStatus.FAILURE, stage=ProcessingStage.CLIP_RENDER, message="Clip rendering failed for this highlight."))
                continue

            percent = 60 + (35 * candidate_index / max(1, len(candidates)))
            progress(JobStatus.CONVERTING_VERTICAL, percent, f"Converting short #{candidate_index}/{len(candidates)} to vertical format")
            try:
                vertical_video = self.vertical_video_service.convert_to_vertical(
                    clip.file_path,
                    VerticalVideoRequest(width=req.vertical_width, height=req.vertical_height),
                    output_filename=f"short_{candidate_index:03d}.mp4",
                )
                self.output_validation_service.validate_video(
                    vertical_video.file_path,
                    expected_duration_seconds=candidate.duration_seconds,
                    expected_width=req.vertical_width,
                    expected_height=req.vertical_height,
                )
            except Exception as exc:
                logger.error("Clip %s vertical render failed (%s)", candidate_index, type(exc).__name__)
                clip_outcomes.append(ClipProcessingOutcome(index=candidate_index, candidate=candidate, status=OutcomeStatus.FAILURE, stage=ProcessingStage.VERTICAL_RENDER, message="Vertical rendering failed for this clip."))
                continue

            caption_track: Optional[CaptionTrack] = None
            captioned_path: Optional[str] = None
            captions_present = False
            short_warnings: list[str] = []
            final_path = vertical_video.file_path
            clip_status = OutcomeStatus.SUCCESS
            clip_stage = ProcessingStage.OUTPUT_VALIDATION
            clip_message = "Clip rendered and validated successfully."
            if vertical_video.processing_warning:
                short_warnings.append(vertical_video.processing_warning)
                warnings.append(vertical_video.processing_warning)
                framing_fallbacks += 1
                clip_status = OutcomeStatus.WARNING
                clip_stage = ProcessingStage.VERTICAL_RENDER
                clip_message = vertical_video.processing_warning

            if req.include_captions:
                progress(JobStatus.ADDING_CAPTIONS, percent, f"Adding captions to short #{candidate_index}/{len(candidates)}")
                try:
                    result = self.caption_service.extract_short_captions(
                        transcript=transcript,
                        start_seconds=candidate.start_seconds,
                        end_seconds=candidate.end_seconds,
                        max_chars_per_line=38,
                    )
                    caption_track = result if isinstance(result, CaptionTrack) else CaptionService().extract_short_captions(
                        transcript, candidate.start_seconds, candidate.end_seconds, 38
                    )
                    if not caption_track.segments:
                        raise ValueError("Caption extraction returned no segments")
                    captioned_video = self.caption_burn_service.burn_captions(
                        vertical_video.file_path,
                        caption_track,
                        preset=req.caption_preset,
                        enable_karaoke=getattr(req, "enable_karaoke", True),
                        karaoke_active_color=getattr(req, "karaoke_active_color", None),
                        output_filename=f"short_{candidate_index:03d}.mp4",
                    )
                    self.output_validation_service.validate_video(
                        captioned_video.file_path,
                        expected_duration_seconds=candidate.duration_seconds,
                        expected_width=req.vertical_width,
                        expected_height=req.vertical_height,
                    )
                    captioned_path = captioned_video.file_path
                    final_path = captioned_path
                    captions_present = True
                except Exception as exc:
                    logger.error("Clip %s caption rendering failed (%s)", candidate_index, type(exc).__name__)
                    message = "Caption rendering failed; the uncaptioned video is available."
                    short_warnings.append(message)
                    warnings.append(message)
                    clip_status = OutcomeStatus.WARNING
                    clip_stage = ProcessingStage.CAPTIONS
                    clip_message = message

            short_index = len(generated_shorts) + 1
            generated_shorts.append(GeneratedShort(
                index=short_index,
                candidate=candidate,
                source_clip_path=clip.file_path,
                vertical_clip_path=vertical_video.file_path,
                captioned_clip_path=captioned_path,
                final_file_path=final_path,
                framing_type=vertical_video.framing_type or FramingType.CENTER_CROP,
                caption_preset=req.caption_preset if captions_present else None,
                is_karaoke=bool(captions_present and getattr(req, "enable_karaoke", True)),
                caption_track=caption_track,
                captions_present=captions_present,
                warnings=short_warnings,
            ))
            clip_outcomes.append(ClipProcessingOutcome(index=candidate_index, candidate=candidate, status=clip_status, stage=clip_stage, message=clip_message, generated_short_index=short_index))

        if not generated_shorts:
            raise ShortsGenerationError("All candidate short rendering attempts failed.", stage=ProcessingStage.VERTICAL_RENDER)

        if clip_render_failures:
            message = f"{clip_render_failures} selected clip(s) failed during initial rendering."
            warnings.append(message)
            outcomes.append(StageOutcome(stage=ProcessingStage.CLIP_RENDER, status=OutcomeStatus.WARNING, message=message))
        else:
            outcomes.append(StageOutcome(stage=ProcessingStage.CLIP_RENDER, status=OutcomeStatus.SUCCESS, message="All selected clips were rendered."))

        failed_vertical = sum(o.stage == ProcessingStage.VERTICAL_RENDER and o.status == OutcomeStatus.FAILURE for o in clip_outcomes)
        failed_captions = sum(o.stage == ProcessingStage.CAPTIONS for o in clip_outcomes)
        outcomes.append(StageOutcome(
            stage=ProcessingStage.VERTICAL_RENDER,
            status=OutcomeStatus.WARNING if failed_vertical or framing_fallbacks else OutcomeStatus.SUCCESS,
            message=(
                f"{failed_vertical} clip(s) failed vertical rendering."
                if failed_vertical
                else f"{framing_fallbacks} clip(s) used center-crop fallback."
                if framing_fallbacks
                else "Vertical rendering completed."
            ),
        ))
        if req.include_captions:
            outcomes.append(StageOutcome(
                stage=ProcessingStage.CAPTIONS,
                status=OutcomeStatus.WARNING if failed_captions else OutcomeStatus.SUCCESS,
                message=f"{failed_captions} clip(s) use an uncaptioned fallback." if failed_captions else "Caption rendering completed.",
            ))
        outcomes.append(StageOutcome(stage=ProcessingStage.OUTPUT_VALIDATION, status=OutcomeStatus.SUCCESS, message="All available final videos passed media validation."))

        try:
            from app.services.observability import default_metrics_collector
            default_metrics_collector.record_shorts_metrics(
                requested=req.number_of_clips,
                generated=len(generated_shorts),
                failed=len(candidates) - len(generated_shorts),
            )
        except Exception as exc:
            logger.warning("Could not record generation metrics (%s)", type(exc).__name__)

        progress(JobStatus.ADDING_CAPTIONS, 95, f"Finalizing {len(generated_shorts)} generated shorts")
        return ShortsGenerationResult(
            source_video=ingested_video,
            metadata=metadata,
            transcript=transcript,
            candidates=candidates,
            generated_shorts=generated_shorts,
            stage_outcomes=outcomes,
            clip_outcomes=clip_outcomes,
            warnings=list(dict.fromkeys(warnings)),
            highlight_method=highlight_method,
        )
