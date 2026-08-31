"""Asynchronous job runner service using background thread pools.

This module provides the `JobRunnerService` for executing `ShortsGenerationService`
pipelines in the background without blocking FastAPI HTTP requests.

Each submitted job receives its own `ShortsGenerationService` instance wired
to job-scoped output directories under the configured media root:

    outputs/jobs/{job_id}/source/     ← source video copy
    outputs/jobs/{job_id}/clips/      ← raw highlight clips
    outputs/jobs/{job_id}/vertical/   ← 9:16 vertical clips
    outputs/jobs/{job_id}/captioned/  ← caption-burned final clips
"""

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Optional
import shutil

from app.models import JobStatus, ShortsGenerationRequest, VideoSourceType
from app.services.caption_burn_service import CaptionBurnService
from app.services.caption_service import CaptionService
from app.services.highlight_clip_service import HighlightClipService
from app.services.highlight_scoring_service import HighlightScoringService
from app.services.job_service import JobService, default_job_service
from app.services.media_storage_service import MediaStorageService, default_media_storage
from app.services.shorts_generation_service import ShortsGenerationService
from app.services.transcription_service import FasterWhisperTranscriptionProvider, TranscriptionService
from app.services.vertical_video_service import VerticalVideoService
from app.services.video_clip_service import VideoClipService
from app.services.video_ingestion_service import VideoIngestionService
from app.services.video_metadata_service import VideoMetadataService


class JobRunnerService:
    """Service responsible for executing video processing jobs asynchronously in background threads."""

    def __init__(
        self,
        job_service: Optional[JobService] = None,
        shorts_service: Optional[ShortsGenerationService] = None,
        max_workers: int = 4,
        media_storage: Optional[MediaStorageService] = None,
    ) -> None:
        self.job_service = job_service or default_job_service
        self.media_storage = media_storage or default_media_storage

        # If a pre-built shorts_service is injected (e.g. in tests that supply
        # mocks), store it for use when no per-job wiring is possible.
        self._shared_shorts_service = shorts_service

        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="shorts-job-runner")

    def _build_job_shorts_service(self, job_id: str) -> ShortsGenerationService:
        """Construct a ShortsGenerationService with output dirs scoped to *job_id*.

        Each stage writes into its own subdirectory under
        ``{media_root}/jobs/{job_id}/``.
        """
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

    def _execute_job_pipeline(self, job_id: str, request: ShortsGenerationRequest) -> None:
        """Worker function executed inside the background thread pool."""

        def on_stage_progress(status: JobStatus, progress_percent: float, message: str) -> None:
            try:
                self.job_service.update_progress(
                    job_id=job_id,
                    status=status,
                    progress_percent=progress_percent,
                    message=message,
                )
            except Exception:
                pass

        try:
            on_stage_progress(JobStatus.INGESTING, 10.0, "Starting video ingestion")

            # --- Copy uploaded source video into job-scoped source dir ---
            if (
                request.source.type == VideoSourceType.UPLOAD
                and Path(request.source.location).is_file()
            ):
                try:
                    src = Path(request.source.location)
                    dest = self.media_storage.copy_to_job_dir(
                        source_path=src,
                        job_id=job_id,
                        subdir=MediaStorageService.SOURCE_SUBDIR,
                        filename=src.name,
                    )
                    # Rebuild request with the job-scoped source path so pipeline
                    # services reference the copy inside the job directory.
                    from app.models import VideoSource
                    request = request.model_copy(
                        update={"source": VideoSource(type=request.source.type, location=str(dest))}
                    )
                except Exception:
                    # Non-fatal: fall back to original path if copy fails
                    pass

            # --- Use injected service (test mocks) or build a job-scoped one ---
            if self._shared_shorts_service is not None:
                shorts_service = self._shared_shorts_service
            else:
                shorts_service = self._build_job_shorts_service(job_id)

            result = shorts_service.generate(
                source=request,
                progress_callback=on_stage_progress,
            )

            self.job_service.complete_job(job_id=job_id, result=result)

        except Exception as exc:
            err_msg = str(exc) or "Unexpected error during pipeline execution"
            try:
                self.job_service.fail_job(job_id=job_id, error=err_msg)
            except Exception:
                pass

    def submit_job(self, job_id: str, request: ShortsGenerationRequest) -> Future:
        """Submit a registered job for asynchronous background processing."""
        return self._executor.submit(self._execute_job_pipeline, job_id, request)

    def shutdown(self, wait: bool = False) -> None:
        """Shut down the background thread pool executor."""
        self._executor.shutdown(wait=wait)


# Global default instance
default_job_runner = JobRunnerService()
