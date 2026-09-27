"""Asynchronous job runner service using background queues or thread pools.

This module provides the `JobRunnerService` for executing `ShortsGenerationService`
pipelines in the background without blocking FastAPI HTTP requests.

Supports both distributed Redis queues (with independent worker daemons) and
in-process `ThreadPoolExecutor` execution for local development and fallback.
"""

from concurrent.futures import Future, ThreadPoolExecutor
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from app.models import JobStatus, OutcomeStatus, ProcessingStage, ShortsGenerationRequest, StageOutcome, VideoSourceType
from app.services.caption_burn_service import CaptionBurnService
from app.services.caption_service import CaptionService
from app.services.highlight_clip_service import HighlightClipService
from app.services.highlight_scoring_service import HighlightScoringService
from app.services.job_service import JobService, default_job_service
from app.services.media_storage_service import CloudSyncReport, MediaStorageService, default_media_storage
from app.services.media_asset_service import MediaAssetService, default_media_asset_service
from app.services.queue_service import (
    JobQueueBase,
    QueueBackend,
    QueueConfig,
    create_job_queue,
    default_job_queue,
)
from app.services.shorts_generation_service import ShortsGenerationError, ShortsGenerationService
from app.services.transcription_service import FasterWhisperTranscriptionProvider, TranscriptionService
from app.services.vertical_video_service import VerticalVideoService
from app.services.video_clip_service import VideoClipService
from app.services.video_ingestion_service import VideoIngestionService
from app.services.video_metadata_service import VideoMetadataService

logger = logging.getLogger(__name__)


class JobRunnerService:
    """Service responsible for executing video processing jobs asynchronously."""

    def __init__(
        self,
        job_service: Optional[JobService] = None,
        shorts_service: Optional[ShortsGenerationService] = None,
        max_workers: int = 4,
        media_storage: Optional[MediaStorageService] = None,
        asset_service: Optional[MediaAssetService] = None,
        queue: Optional[JobQueueBase] = None,
    ) -> None:
        self.job_service = job_service or default_job_service
        self.media_storage = media_storage or default_media_storage
        self.asset_service = asset_service or default_media_asset_service
        self.queue = queue if queue is not None else default_job_queue

        # If a pre-built shorts_service is injected (e.g. in tests that supply mocks)
        self._shared_shorts_service = shorts_service

        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="shorts-job-runner")

    def _build_job_shorts_service(self, job_id: str) -> ShortsGenerationService:
        """Construct a ShortsGenerationService with output dirs scoped to *job_id*."""
        clips_dir = self.media_storage.get_job_subdir(job_id, MediaStorageService.CLIPS_SUBDIR)
        vertical_dir = self.media_storage.get_job_subdir(job_id, MediaStorageService.VERTICAL_SUBDIR)
        captioned_dir = self.media_storage.get_job_subdir(job_id, MediaStorageService.CAPTIONED_SUBDIR)

        caption_service = CaptionService()
        return ShortsGenerationService(
            ingestion_service=VideoIngestionService(),
            metadata_service=VideoMetadataService(),
            transcription_service=TranscriptionService(
                provider=FasterWhisperTranscriptionProvider()
            ),
            highlight_scoring_service=HighlightScoringService(),
            highlight_clip_service=HighlightClipService(
                video_clip_service=VideoClipService(output_dir=clips_dir)
            ),
            vertical_video_service=VerticalVideoService(output_dir=vertical_dir),
            caption_service=caption_service,
            caption_burn_service=CaptionBurnService(
                output_dir=captioned_dir,
                caption_service=caption_service,
            ),
        )

    def execute_job_pipeline(self, job_id: str, request: ShortsGenerationRequest) -> None:
        """Execute the full video processing pipeline for a job."""

        def on_stage_progress(status: JobStatus, progress_percent: float, message: str) -> None:
            try:
                self.job_service.update_progress(
                    job_id=job_id,
                    status=status,
                    progress_percent=progress_percent,
                    message=message,
                )
            except Exception:
                logger.warning("Job %s progress update failed at status %s", job_id, status.value)

        import time
        from app.services.observability import default_metrics_collector, log_audit_event, set_job_id

        set_job_id(job_id)
        default_metrics_collector.record_job_event("processing")
        log_audit_event("job.started", "success", resource_id=job_id)
        t_start = time.perf_counter()

        try:
            on_stage_progress(JobStatus.INGESTING, 10.0, "Starting video ingestion")

            # --- Copy uploaded source video into job-scoped source dir ---
            if request.source.type == VideoSourceType.UPLOAD:
                try:
                    if request.source.asset_id:
                        if not request.user_id:
                            raise PermissionError("Upload asset job is missing its owner.")
                        src = self.asset_service.resolve_owned_asset(
                            request.source.asset_id,
                            request.user_id,
                        )
                    elif request.source.location:
                        # Legacy persisted jobs may still contain an internal path.
                        src = Path(request.source.location)
                        if not src.is_file():
                            raise FileNotFoundError(f"Legacy upload source was not found: {src}")
                    else:
                        raise FileNotFoundError("Upload source is missing an asset reference.")
                    dest = self.media_storage.copy_to_job_dir(
                        source_path=src,
                        job_id=job_id,
                        subdir=MediaStorageService.SOURCE_SUBDIR,
                        filename=src.name,
                    )
                    from app.models import VideoSource
                    request = request.model_copy(
                        update={
                            "source": VideoSource(
                                type=request.source.type,
                                location=str(dest),
                                asset_id=request.source.asset_id,
                            )
                        }
                    )
                except Exception as exc:
                    raise RuntimeError(f"Failed to resolve uploaded source: {exc}") from exc

            # --- Use injected service (test mocks) or build a job-scoped one ---
            if self._shared_shorts_service is not None:
                shorts_service = self._shared_shorts_service
            else:
                shorts_service = self._build_job_shorts_service(job_id)

            result = shorts_service.generate(
                source=request,
                progress_callback=on_stage_progress,
            )

            # An injected or URL-ingestion service may return a source outside the
            # job media root. Preserve it under the owned job directory before
            # normalization so no absolute host path reaches persisted API data.
            try:
                self.media_storage.to_relative_path(result.source_video.file_path)
            except Exception:
                try:
                    owned_source = self.media_storage.copy_to_job_dir(
                        source_path=result.source_video.file_path,
                        job_id=job_id,
                        subdir=MediaStorageService.SOURCE_SUBDIR,
                    )
                    result = result.model_copy(update={
                        "source_video": result.source_video.model_copy(
                            update={"file_path": str(owned_source)}
                        )
                    })
                except Exception as exc:
                    raise ShortsGenerationError(
                        "Source media could not be finalized.",
                        diagnostic=str(exc),
                        stage=ProcessingStage.SOURCE_INGESTION,
                    ) from exc

            def ensure_owned_artifact(path: str, subdir: str) -> str:
                try:
                    self.media_storage.to_relative_path(path)
                    return path
                except Exception:
                    return str(self.media_storage.copy_to_job_dir(
                        source_path=path,
                        job_id=job_id,
                        subdir=subdir,
                    ))

            owned_shorts = []
            try:
                for short in result.generated_shorts:
                    source_clip = ensure_owned_artifact(short.source_clip_path, MediaStorageService.CLIPS_SUBDIR)
                    vertical_clip = ensure_owned_artifact(short.vertical_clip_path, MediaStorageService.VERTICAL_SUBDIR)
                    captioned_clip = (
                        ensure_owned_artifact(short.captioned_clip_path, MediaStorageService.CAPTIONED_SUBDIR)
                        if short.captioned_clip_path
                        else None
                    )
                    if short.final_file_path == short.captioned_clip_path and captioned_clip:
                        final_file = captioned_clip
                    elif short.final_file_path == short.vertical_clip_path:
                        final_file = vertical_clip
                    else:
                        final_file = ensure_owned_artifact(short.final_file_path, MediaStorageService.CAPTIONED_SUBDIR)
                    owned_shorts.append(short.model_copy(update={
                        "source_clip_path": source_clip,
                        "vertical_clip_path": vertical_clip,
                        "captioned_clip_path": captioned_clip,
                        "final_file_path": final_file,
                    }))
                result = result.model_copy(update={"generated_shorts": owned_shorts})
            except Exception as exc:
                raise ShortsGenerationError(
                    "Generated media could not be finalized.",
                    diagnostic=str(exc),
                    stage=ProcessingStage.OUTPUT_VALIDATION,
                ) from exc

            # --- Cloud Storage sync (uploads generated artifacts if S3/R2 configured) ---
            try:
                sync_report = self.media_storage.sync_job_to_cloud(job_id)
            except Exception as exc:
                logger.error("Job %s storage_sync failed (%s)", job_id, type(exc).__name__)
                raise ShortsGenerationError(
                    "Media storage synchronization failed.",
                    diagnostic=str(exc),
                    stage=ProcessingStage.STORAGE_SYNC,
                ) from exc

            if isinstance(sync_report, CloudSyncReport):
                if sync_report.failure_count and sync_report.required:
                    raise ShortsGenerationError(
                        "Required cloud storage synchronization failed.",
                        diagnostic=f"{sync_report.failure_count} artifact upload(s) failed",
                        stage=ProcessingStage.STORAGE_SYNC,
                    )
                if sync_report.failure_count:
                    warning = "Cloud synchronization was incomplete; local media remains available."
                    result = result.model_copy(update={
                        "warnings": list(dict.fromkeys([*result.warnings, warning])),
                        "stage_outcomes": [
                            *result.stage_outcomes,
                            StageOutcome(stage=ProcessingStage.STORAGE_SYNC, status=OutcomeStatus.WARNING, message=warning),
                        ],
                        "completion_state": OutcomeStatus.WARNING,
                    })
                elif sync_report.attempted:
                    result = result.model_copy(update={
                        "stage_outcomes": [
                            *result.stage_outcomes,
                            StageOutcome(stage=ProcessingStage.STORAGE_SYNC, status=OutcomeStatus.SUCCESS, message="Cloud synchronization completed."),
                        ]
                    })

            # --- Normalize all artifact paths to relative paths before persistence ---
            try:
                result = self.media_storage.normalize_result_paths(result)
            except Exception as exc:
                raise ShortsGenerationError(
                    "Generated media paths could not be finalized.",
                    diagnostic=str(exc),
                    stage=ProcessingStage.OUTPUT_VALIDATION,
                ) from exc

            duration_ms = (time.perf_counter() - t_start) * 1000.0
            default_metrics_collector.record_stage_duration("e2e_pipeline", duration_ms)
            default_metrics_collector.record_job_event("completed")
            log_audit_event(
                "job.completed",
                "success",
                resource_id=job_id,
                details={"duration_ms": round(duration_ms, 2)},
            )

            self.job_service.complete_job(job_id=job_id, result=result)

        except Exception as exc:
            duration_ms = (time.perf_counter() - t_start) * 1000.0
            if isinstance(exc, ShortsGenerationError):
                err_msg = exc.user_message
                stage = exc.stage.value if exc.stage else "pipeline"
            else:
                err_msg = "Video processing failed unexpectedly."
                stage = "pipeline"
            logger.error("Job %s failed at stage %s: %s (%s)", job_id, stage, err_msg, type(exc).__name__)
            default_metrics_collector.record_job_event("failed")
            log_audit_event("job.failed", "error", resource_id=job_id, details={"stage": stage, "duration_ms": round(duration_ms, 2)})
            try:
                self.job_service.fail_job(job_id=job_id, error=err_msg)
            except Exception as persist_exc:
                logger.error("Job %s failure status could not be persisted (%s)", job_id, type(persist_exc).__name__)
            raise

    def submit_job(self, job_id: str, request: ShortsGenerationRequest) -> Future:
        """Submit a registered job for asynchronous background processing."""
        # If queue is Redis, enqueue to distributed queue
        from app.services.queue_service import RedisJobQueue
        if isinstance(self.queue, RedisJobQueue):
            payload = json_payload = request.model_dump(mode="json")
            self.queue.enqueue(job_id, payload)
            # Return an already resolved future for backward compatibility with tests expecting Future return type
            fut: Future = Future()
            fut.set_result(None)
            return fut

        # In-process ThreadPool execution
        return self._executor.submit(self._execute_job_pipeline, job_id, request)

    def _execute_job_pipeline(self, job_id: str, request: ShortsGenerationRequest) -> None:
        """Internal wrapper called by threadpool executor."""
        try:
            self.execute_job_pipeline(job_id, request)
        except Exception as exc:
            # execute_job_pipeline already persisted and logged the safe failure.
            logger.debug("Background job %s exited after recorded failure (%s)", job_id, type(exc).__name__)

    def shutdown(self, wait: bool = False) -> None:
        """Shut down the background thread pool executor."""
        self._executor.shutdown(wait=wait)


# Global default instance
default_job_runner = JobRunnerService()
