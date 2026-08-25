"""Unit tests for JobRunnerService asynchronous background execution.

These tests verify background job execution, non-blocking submission, progress propagation,
error handling, and concurrent job handling using mock services.
"""

from pathlib import Path
import time
from unittest.mock import MagicMock
import pytest

from app.models import (
    GeneratedHighlightClip,
    GeneratedShort,
    HighlightCandidate,
    HighlightScore,
    IngestedVideo,
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
from app.services.job_runner_service import JobRunnerService
from app.services.job_service import JobService
from app.services.shorts_generation_service import ShortsGenerationError, ShortsGenerationService


def make_test_request() -> ShortsGenerationRequest:
    return ShortsGenerationRequest(
        source=VideoSource(type=VideoSourceType.UPLOAD, location="sample_video.mp4"),
        clip_duration_seconds=45.0,
        number_of_clips=1,
    )


def make_test_result() -> ShortsGenerationResult:
    cand = HighlightCandidate(
        start_seconds=10.0,
        end_seconds=40.0,
        duration_seconds=30.0,
        text="Sample text",
        score=HighlightScore(overall=0.9, hook=0.9, emotion=0.8, curiosity=0.8, information_density=0.8),
    )
    short = GeneratedShort(
        index=1,
        candidate=cand,
        source_clip_path="c.mp4",
        vertical_clip_path="v.mp4",
        final_file_path="v.mp4",
    )
    return ShortsGenerationResult(
        source_video=IngestedVideo(file_path="src.mp4"),
        metadata=VideoMetadata(duration_seconds=60.0, width=1920, height=1080, format="mp4", file_size_bytes=1024),
        transcript=TimestampedTranscript(segments=[]),
        candidates=[cand],
        generated_shorts=[short],
    )


class TestJobRunnerService:
    def test_submit_job_executes_asynchronously_and_completes(self):
        job_service = JobService()
        mock_shorts_service = MagicMock(spec=ShortsGenerationService)

        expected_result = make_test_result()

        def mock_generate(source, progress_callback=None, **kwargs):
            if progress_callback:
                progress_callback(JobStatus.TRANSCRIBING, 35.0, "Transcribing")
            return expected_result

        mock_shorts_service.generate.side_effect = mock_generate

        runner = JobRunnerService(job_service=job_service, shorts_service=mock_shorts_service, max_workers=2)
        req = make_test_request()
        job = job_service.create_job(req)

        # Submit job to runner
        future = runner.submit_job(job.job_id, req)

        # Wait for background completion
        future.result(timeout=5.0)

        final_job = job_service.get_job(job.job_id)
        assert final_job is not None
        assert final_job.status == JobStatus.COMPLETED
        assert final_job.progress_percent == 100.0
        assert final_job.result is not None
        assert final_job.completed_at is not None

        runner.shutdown(wait=False)

    def test_pipeline_failure_marks_job_failed(self):
        job_service = JobService()
        mock_shorts_service = MagicMock(spec=ShortsGenerationService)
        mock_shorts_service.generate.side_effect = ShortsGenerationError("FFmpeg execution timed out")

        runner = JobRunnerService(job_service=job_service, shorts_service=mock_shorts_service, max_workers=2)
        req = make_test_request()
        job = job_service.create_job(req)

        future = runner.submit_job(job.job_id, req)
        future.result(timeout=5.0)

        final_job = job_service.get_job(job.job_id)
        assert final_job is not None
        assert final_job.status == JobStatus.FAILED
        assert "FFmpeg execution timed out" in (final_job.error or "")

        runner.shutdown(wait=False)

    def test_runner_does_not_block_caller(self):
        job_service = JobService()
        mock_shorts_service = MagicMock(spec=ShortsGenerationService)

        # Simulate a slow pipeline execution
        def slow_generate(source, **kwargs):
            time.sleep(0.5)
            return make_test_result()

        mock_shorts_service.generate.side_effect = slow_generate

        runner = JobRunnerService(job_service=job_service, shorts_service=mock_shorts_service, max_workers=2)
        req = make_test_request()
        job = job_service.create_job(req)

        start_time = time.time()
        future = runner.submit_job(job.job_id, req)
        submission_time = time.time() - start_time

        # submit_job must return immediately (well under 0.1s)
        assert submission_time < 0.2

        future.result(timeout=5.0)
        runner.shutdown(wait=False)

    def test_multiple_concurrent_jobs_run_and_complete(self):
        job_service = JobService()
        mock_shorts_service = MagicMock(spec=ShortsGenerationService)
        mock_shorts_service.generate.return_value = make_test_result()

        runner = JobRunnerService(job_service=job_service, shorts_service=mock_shorts_service, max_workers=4)

        jobs = [job_service.create_job(make_test_request()) for _ in range(3)]
        futures = [runner.submit_job(j.job_id, make_test_request()) for j in jobs]

        for f in futures:
            f.result(timeout=5.0)

        for j in jobs:
            completed_job = job_service.get_job(j.job_id)
            assert completed_job is not None
            assert completed_job.status == JobStatus.COMPLETED

        runner.shutdown(wait=False)
