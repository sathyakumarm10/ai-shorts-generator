"""Unit tests for JobService in-memory repository and state transition validation.

These tests verify job creation, retrieval, progress updates, state machine enforcement,
completion, failure handling, and thread safety.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from app.models import (
    GeneratedHighlightClip,
    GeneratedShort,
    HighlightCandidate,
    HighlightScore,
    IngestedVideo,
    JobProgress,
    JobRecord,
    JobStatus,
    ShortsGenerationRequest,
    ShortsGenerationResult,
    TimestampedTranscript,
    TranscriptSegment,
    VideoMetadata,
    VideoSource,
    VideoSourceType,
)
from app.services.job_service import JobError, JobService


# ---------------------------------------------------------------------------
# Test Helpers & Fixtures
# ---------------------------------------------------------------------------


def make_test_request() -> ShortsGenerationRequest:
    source = VideoSource(type=VideoSourceType.UPLOAD, location="sample_video.mp4")
    return ShortsGenerationRequest(
        source=source,
        clip_duration_seconds=45.0,
        number_of_clips=2,
    )


def make_test_result() -> ShortsGenerationResult:
    cand = HighlightCandidate(
        start_seconds=10.0,
        end_seconds=40.0,
        duration_seconds=30.0,
        text="Highlight text",
        score=HighlightScore(overall=0.9, hook=0.9, emotion=0.8, curiosity=0.8, information_density=0.8),
    )
    short = GeneratedShort(
        index=1,
        candidate=cand,
        source_clip_path="c.mp4",
        vertical_clip_path="v.mp4",
        captioned_clip_path="cap.mp4",
        final_file_path="cap.mp4",
    )
    return ShortsGenerationResult(
        source_video=IngestedVideo(file_path="source.mp4"),
        metadata=VideoMetadata(duration_seconds=60.0, width=1920, height=1080, format="mp4", file_size_bytes=1024),
        transcript=TimestampedTranscript(segments=[]),
        candidates=[cand],
        generated_shorts=[short],
    )


# ---------------------------------------------------------------------------
# JobProgress & JobRecord Model Tests
# ---------------------------------------------------------------------------


class TestJobModels:
    def test_valid_job_progress(self):
        progress = JobProgress(status=JobStatus.TRANSCRIBING, progress_percent=35.0, message="Transcribing speech")
        assert progress.status == JobStatus.TRANSCRIBING
        assert progress.progress_percent == 35.0
        assert progress.message == "Transcribing speech"

    def test_reject_invalid_progress_percent(self):
        with pytest.raises(ValidationError):
            JobProgress(status=JobStatus.INGESTING, progress_percent=-5.0, message="Underflow")
        with pytest.raises(ValidationError):
            JobProgress(status=JobStatus.INGESTING, progress_percent=105.0, message="Overflow")
        with pytest.raises(ValidationError):
            JobProgress(status=JobStatus.INGESTING, progress_percent=float("nan"), message="NaN")

    def test_reject_empty_message(self):
        with pytest.raises(ValidationError):
            JobProgress(status=JobStatus.INGESTING, progress_percent=10.0, message="")
        with pytest.raises(ValidationError):
            JobProgress(status=JobStatus.INGESTING, progress_percent=10.0, message="   ")

    def test_valid_job_record(self):
        now = datetime.now(timezone.utc)
        record = JobRecord(
            job_id="job-123",
            status=JobStatus.QUEUED,
            progress_percent=0.0,
            message="Job queued",
            created_at=now,
        )
        assert record.job_id == "job-123"
        assert record.status == JobStatus.QUEUED

    def test_completed_job_requires_completed_at(self):
        now = datetime.now(timezone.utc)
        with pytest.raises(ValidationError):
            JobRecord(
                job_id="job-123",
                status=JobStatus.COMPLETED,
                progress_percent=100.0,
                message="Done",
                created_at=now,
                completed_at=None,
            )

    def test_failed_job_requires_error_message(self):
        now = datetime.now(timezone.utc)
        with pytest.raises(ValidationError):
            JobRecord(
                job_id="job-123",
                status=JobStatus.FAILED,
                progress_percent=20.0,
                message="Failed",
                created_at=now,
                error=None,
            )


# ---------------------------------------------------------------------------
# JobService Functionality Tests
# ---------------------------------------------------------------------------


class TestJobService:
    def test_create_and_get_job(self):
        service = JobService()
        req = make_test_request()

        job = service.create_job(req)
        assert job.job_id is not None
        assert job.status == JobStatus.QUEUED
        assert job.progress_percent == 0.0
        assert job.clip_duration == 45
        assert job.number_of_clips == 2

        fetched = service.get_job(job.job_id)
        assert fetched is not None
        assert fetched.job_id == job.job_id

    def test_get_nonexistent_job_returns_none(self):
        service = JobService()
        assert service.get_job("non-existent-id") is None

    def test_valid_state_transitions_and_progress_updates(self):
        service = JobService()
        req = make_test_request()
        job = service.create_job(req)
        job_id = job.job_id

        # QUEUED -> INGESTING
        job = service.update_progress(job_id, JobStatus.INGESTING, 10.0, "Ingesting video")
        assert job.status == JobStatus.INGESTING
        assert job.progress_percent == 10.0
        assert job.started_at is not None

        # INGESTING -> EXTRACTING_METADATA
        job = service.update_progress(job_id, JobStatus.EXTRACTING_METADATA, 20.0, "Extracting metadata")
        assert job.status == JobStatus.EXTRACTING_METADATA
        assert job.progress_percent == 20.0

        # EXTRACTING_METADATA -> TRANSCRIBING
        job = service.update_progress(job_id, JobStatus.TRANSCRIBING, 35.0, "Transcribing audio")
        assert job.status == JobStatus.TRANSCRIBING

        # TRANSCRIBING -> FINDING_HIGHLIGHTS
        job = service.update_progress(job_id, JobStatus.FINDING_HIGHLIGHTS, 50.0, "Finding highlights")
        assert job.status == JobStatus.FINDING_HIGHLIGHTS

        # Complete job
        result = make_test_result()
        job = service.complete_job(job_id, result)
        assert job.status == JobStatus.COMPLETED
        assert job.progress_percent == 100.0
        assert job.completed_at is not None
        assert job.result is not None

    def test_invalid_state_transitions_raise_job_error(self):
        service = JobService()
        req = make_test_request()
        job = service.create_job(req)
        job_id = job.job_id

        # Mark completed
        service.complete_job(job_id, make_test_result())

        # Attempt to transition from terminal COMPLETED back to TRANSCRIBING
        with pytest.raises(JobError):
            service.update_progress(job_id, JobStatus.TRANSCRIBING, 35.0, "Invalid back-transition")

        # Attempt to fail a completed job
        with pytest.raises(JobError):
            service.fail_job(job_id, "Cannot fail completed job")

    def test_fail_job_from_active_state(self):
        service = JobService()
        req = make_test_request()
        job = service.create_job(req)
        job_id = job.job_id

        service.update_progress(job_id, JobStatus.TRANSCRIBING, 35.0, "Transcribing")
        failed_job = service.fail_job(job_id, "Whisper model execution error")

        assert failed_job.status == JobStatus.FAILED
        assert "Whisper model execution error" in (failed_job.error or "")
        assert failed_job.completed_at is not None

        # Cannot transition out of FAILED
        with pytest.raises(JobError):
            service.update_progress(job_id, JobStatus.GENERATING_CLIPS, 65.0, "Invalid transition")

    def test_thread_safe_concurrent_progress_updates(self):
        service = JobService()
        req = make_test_request()
        job = service.create_job(req)
        job_id = job.job_id

        def worker(percent: int):
            try:
                service.update_progress(
                    job_id,
                    JobStatus.INGESTING,
                    float(percent),
                    f"Progress {percent}%",
                )
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(worker, range(1, 20)))

        final_job = service.get_job(job_id)
        assert final_job is not None
        assert final_job.status == JobStatus.INGESTING
        assert 0.0 <= final_job.progress_percent <= 100.0
