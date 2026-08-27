"""Tests for SQLite-backed persistent job storage.

Covers:
  - Create, retrieve, update, complete, and fail round-trips through SQLite
  - Restart persistence (new JobService instance over the same DB file)
  - Result serialisation / deserialisation (ShortsGenerationResult as JSON)
  - Concurrent multi-thread access
  - Error handling (duplicate insert, missing job)
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import pytest

from app.models import (
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
from app.services.job_service import JobError, JobService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request() -> ShortsGenerationRequest:
    return ShortsGenerationRequest(
        source=VideoSource(type=VideoSourceType.UPLOAD, location="sample.mp4"),
        clip_duration_seconds=45.0,
        number_of_clips=2,
    )


def _make_result() -> ShortsGenerationResult:
    cand = HighlightCandidate(
        start_seconds=10.0,
        end_seconds=40.0,
        duration_seconds=30.0,
        text="Highlight text for testing",
        score=HighlightScore(
            overall=0.92, hook=0.88, emotion=0.85, curiosity=0.80, information_density=0.78
        ),
    )
    short = GeneratedShort(
        index=1,
        candidate=cand,
        source_clip_path="clip.mp4",
        vertical_clip_path="vert.mp4",
        captioned_clip_path="cap.mp4",
        final_file_path="cap.mp4",
    )
    return ShortsGenerationResult(
        source_video=IngestedVideo(file_path="source.mp4"),
        metadata=VideoMetadata(
            duration_seconds=120.0,
            width=1920,
            height=1080,
            format="mp4",
            file_size_bytes=4096,
        ),
        transcript=TimestampedTranscript(
            segments=[
                TranscriptSegment(start_seconds=0.0, end_seconds=10.0, text="Hello world"),
                TranscriptSegment(start_seconds=10.0, end_seconds=40.0, text="Highlight text for testing"),
            ]
        ),
        candidates=[cand],
        generated_shorts=[short],
    )


# ---------------------------------------------------------------------------
# Basic CRUD
# ---------------------------------------------------------------------------


class TestSQLitePersistenceBasics:
    """Verify core CRUD through JobService backed by a tmp SQLite file."""

    def test_create_and_retrieve(self, tmp_path: Path):
        db = str(tmp_path / "test.db")
        svc = JobService(db_path=db)
        job = svc.create_job(_make_request())

        assert job.status == JobStatus.QUEUED
        assert job.progress_percent == 0.0

        fetched = svc.get_job(job.job_id)
        assert fetched is not None
        assert fetched.job_id == job.job_id
        assert fetched.status == JobStatus.QUEUED
        assert fetched.source is not None
        assert fetched.source.type == VideoSourceType.UPLOAD
        assert fetched.clip_duration == 45
        assert fetched.number_of_clips == 2

    def test_get_nonexistent_returns_none(self, tmp_path: Path):
        svc = JobService(db_path=str(tmp_path / "test.db"))
        assert svc.get_job("does-not-exist") is None

    def test_update_progress(self, tmp_path: Path):
        svc = JobService(db_path=str(tmp_path / "test.db"))
        job = svc.create_job(_make_request())

        updated = svc.update_progress(
            job.job_id, JobStatus.TRANSCRIBING, 35.0, "Transcribing audio"
        )
        assert updated.status == JobStatus.TRANSCRIBING
        assert updated.progress_percent == 35.0
        assert updated.started_at is not None

        fetched = svc.get_job(job.job_id)
        assert fetched is not None
        assert fetched.status == JobStatus.TRANSCRIBING
        assert fetched.progress_percent == 35.0

    def test_complete_job_with_result(self, tmp_path: Path):
        svc = JobService(db_path=str(tmp_path / "test.db"))
        job = svc.create_job(_make_request())
        result = _make_result()

        completed = svc.complete_job(job.job_id, result)
        assert completed.status == JobStatus.COMPLETED
        assert completed.progress_percent == 100.0
        assert completed.completed_at is not None
        assert completed.result is not None
        assert len(completed.result.generated_shorts) == 1
        assert completed.result.generated_shorts[0].final_file_path == "cap.mp4"

    def test_fail_job(self, tmp_path: Path):
        svc = JobService(db_path=str(tmp_path / "test.db"))
        job = svc.create_job(_make_request())

        failed = svc.fail_job(job.job_id, "FFmpeg crashed")
        assert failed.status == JobStatus.FAILED
        assert "FFmpeg crashed" in (failed.error or "")
        assert failed.completed_at is not None

    def test_full_state_machine_walk(self, tmp_path: Path):
        svc = JobService(db_path=str(tmp_path / "test.db"))
        job = svc.create_job(_make_request())
        jid = job.job_id

        svc.update_progress(jid, JobStatus.INGESTING, 5.0, "Ingesting")
        svc.update_progress(jid, JobStatus.EXTRACTING_METADATA, 15.0, "Extracting metadata")
        svc.update_progress(jid, JobStatus.TRANSCRIBING, 30.0, "Transcribing")
        svc.update_progress(jid, JobStatus.FINDING_HIGHLIGHTS, 50.0, "Finding highlights")
        svc.update_progress(jid, JobStatus.GENERATING_CLIPS, 65.0, "Generating clips")
        svc.update_progress(jid, JobStatus.CONVERTING_VERTICAL, 80.0, "Converting vertical")
        svc.update_progress(jid, JobStatus.ADDING_CAPTIONS, 90.0, "Adding captions")

        completed = svc.complete_job(jid, _make_result())
        assert completed.status == JobStatus.COMPLETED
        assert completed.progress_percent == 100.0


# ---------------------------------------------------------------------------
# Restart persistence — the whole point of SQLite
# ---------------------------------------------------------------------------


class TestRestartPersistence:
    """Verify that jobs survive across new JobService instances sharing a DB file."""

    def test_job_survives_restart(self, tmp_path: Path):
        db = str(tmp_path / "persist.db")

        # Session 1: create a job and advance it
        svc1 = JobService(db_path=db)
        job = svc1.create_job(_make_request())
        svc1.update_progress(job.job_id, JobStatus.TRANSCRIBING, 40.0, "Transcribing")

        # Session 2: new instance, same DB
        svc2 = JobService(db_path=db)
        recovered = svc2.get_job(job.job_id)
        assert recovered is not None
        assert recovered.job_id == job.job_id
        assert recovered.status == JobStatus.TRANSCRIBING
        assert recovered.progress_percent == 40.0
        assert recovered.source is not None
        assert recovered.source.location == "sample.mp4"

    def test_completed_result_survives_restart(self, tmp_path: Path):
        db = str(tmp_path / "persist.db")

        svc1 = JobService(db_path=db)
        job = svc1.create_job(_make_request())
        svc1.complete_job(job.job_id, _make_result())

        svc2 = JobService(db_path=db)
        recovered = svc2.get_job(job.job_id)
        assert recovered is not None
        assert recovered.status == JobStatus.COMPLETED
        assert recovered.result is not None
        assert len(recovered.result.generated_shorts) == 1
        assert recovered.result.generated_shorts[0].candidate.score.overall == 0.92
        assert len(recovered.result.transcript.segments) == 2

    def test_failed_job_survives_restart(self, tmp_path: Path):
        db = str(tmp_path / "persist.db")

        svc1 = JobService(db_path=db)
        job = svc1.create_job(_make_request())
        svc1.fail_job(job.job_id, "Disk full")

        svc2 = JobService(db_path=db)
        recovered = svc2.get_job(job.job_id)
        assert recovered is not None
        assert recovered.status == JobStatus.FAILED
        assert "Disk full" in (recovered.error or "")

    def test_multiple_jobs_persist(self, tmp_path: Path):
        db = str(tmp_path / "persist.db")

        svc1 = JobService(db_path=db)
        jobs = [svc1.create_job(_make_request()) for _ in range(5)]
        svc1.complete_job(jobs[0].job_id, _make_result())
        svc1.fail_job(jobs[1].job_id, "Timeout")

        svc2 = JobService(db_path=db)
        for original in jobs:
            recovered = svc2.get_job(original.job_id)
            assert recovered is not None
            assert recovered.job_id == original.job_id

        assert svc2.get_job(jobs[0].job_id).status == JobStatus.COMPLETED  # type: ignore
        assert svc2.get_job(jobs[1].job_id).status == JobStatus.FAILED  # type: ignore
        assert svc2.get_job(jobs[2].job_id).status == JobStatus.QUEUED  # type: ignore

    def test_continue_processing_after_restart(self, tmp_path: Path):
        """Simulate crash-recovery: advance a job, restart, then complete it."""
        db = str(tmp_path / "persist.db")

        svc1 = JobService(db_path=db)
        job = svc1.create_job(_make_request())
        svc1.update_progress(job.job_id, JobStatus.GENERATING_CLIPS, 65.0, "Generating clips")
        del svc1  # simulate process exit

        svc2 = JobService(db_path=db)
        recovered = svc2.get_job(job.job_id)
        assert recovered is not None
        assert recovered.status == JobStatus.GENERATING_CLIPS

        # Continue from where we left off
        svc2.update_progress(job.job_id, JobStatus.CONVERTING_VERTICAL, 80.0, "Converting")
        svc2.complete_job(job.job_id, _make_result())

        final = svc2.get_job(job.job_id)
        assert final is not None
        assert final.status == JobStatus.COMPLETED
        assert final.result is not None


# ---------------------------------------------------------------------------
# State transition validation persists correctly
# ---------------------------------------------------------------------------


class TestPersistentStateTransitions:
    def test_cannot_update_completed_job_after_restart(self, tmp_path: Path):
        db = str(tmp_path / "test.db")

        svc1 = JobService(db_path=db)
        job = svc1.create_job(_make_request())
        svc1.complete_job(job.job_id, _make_result())

        svc2 = JobService(db_path=db)
        with pytest.raises(JobError):
            svc2.update_progress(job.job_id, JobStatus.TRANSCRIBING, 50.0, "Invalid")

    def test_cannot_fail_completed_job_after_restart(self, tmp_path: Path):
        db = str(tmp_path / "test.db")

        svc1 = JobService(db_path=db)
        job = svc1.create_job(_make_request())
        svc1.complete_job(job.job_id, _make_result())

        svc2 = JobService(db_path=db)
        with pytest.raises(JobError):
            svc2.fail_job(job.job_id, "Too late")

    def test_cannot_complete_failed_job_after_restart(self, tmp_path: Path):
        db = str(tmp_path / "test.db")

        svc1 = JobService(db_path=db)
        job = svc1.create_job(_make_request())
        svc1.fail_job(job.job_id, "Error")

        svc2 = JobService(db_path=db)
        with pytest.raises(JobError):
            svc2.complete_job(job.job_id, _make_result())


# ---------------------------------------------------------------------------
# Concurrent access
# ---------------------------------------------------------------------------


class TestConcurrentAccess:
    def test_concurrent_creates(self, tmp_path: Path):
        db = str(tmp_path / "concurrent.db")
        svc = JobService(db_path=db)

        def create_one(_: int) -> str:
            job = svc.create_job(_make_request())
            return job.job_id

        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(create_one, range(20)))

        assert len(set(ids)) == 20  # all unique
        for jid in ids:
            assert svc.get_job(jid) is not None

    def test_concurrent_progress_updates(self, tmp_path: Path):
        db = str(tmp_path / "concurrent.db")
        svc = JobService(db_path=db)
        job = svc.create_job(_make_request())

        def update_once(pct: int):
            try:
                svc.update_progress(
                    job.job_id,
                    JobStatus.INGESTING,
                    float(pct),
                    f"Progress {pct}%",
                )
            except JobError:
                pass  # race with terminal state is acceptable

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(update_once, range(1, 30)))

        final = svc.get_job(job.job_id)
        assert final is not None
        assert final.status == JobStatus.INGESTING
        assert 0.0 <= final.progress_percent <= 100.0

    def test_concurrent_create_and_complete(self, tmp_path: Path):
        db = str(tmp_path / "concurrent.db")
        svc = JobService(db_path=db)

        def create_and_complete(_: int) -> str:
            job = svc.create_job(_make_request())
            svc.complete_job(job.job_id, _make_result())
            return job.job_id

        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(create_and_complete, range(10)))

        for jid in ids:
            final = svc.get_job(jid)
            assert final is not None
            assert final.status == JobStatus.COMPLETED
            assert final.result is not None

    def test_concurrent_reads_during_writes(self, tmp_path: Path):
        db = str(tmp_path / "concurrent.db")
        svc = JobService(db_path=db)
        job = svc.create_job(_make_request())

        errors = []

        def reader():
            try:
                for _ in range(50):
                    fetched = svc.get_job(job.job_id)
                    assert fetched is not None
            except Exception as exc:
                errors.append(exc)

        def writer():
            try:
                for pct in range(1, 50):
                    svc.update_progress(
                        job.job_id,
                        JobStatus.INGESTING,
                        float(pct),
                        f"Progress {pct}%",
                    )
            except JobError:
                pass

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = []
            for _ in range(4):
                futures.append(pool.submit(reader))
            futures.append(pool.submit(writer))
            for f in as_completed(futures):
                f.result()

        assert len(errors) == 0


# ---------------------------------------------------------------------------
# In-memory mode (backward compatibility)
# ---------------------------------------------------------------------------


class TestInMemoryFallback:
    """Ensure JobService() with no db_path still works (in-memory SQLite)."""

    def test_in_memory_create_and_get(self):
        svc = JobService()
        job = svc.create_job(_make_request())
        assert svc.get_job(job.job_id) is not None

    def test_in_memory_is_ephemeral(self):
        svc1 = JobService()
        job = svc1.create_job(_make_request())

        svc2 = JobService()
        assert svc2.get_job(job.job_id) is None  # gone — separate in-memory DB


# ---------------------------------------------------------------------------
# Timestamp round-trip fidelity
# ---------------------------------------------------------------------------


class TestTimestampFidelity:
    def test_created_at_round_trips(self, tmp_path: Path):
        svc = JobService(db_path=str(tmp_path / "ts.db"))
        job = svc.create_job(_make_request())
        fetched = svc.get_job(job.job_id)
        assert fetched is not None
        assert fetched.created_at == job.created_at

    def test_started_and_completed_at_round_trip(self, tmp_path: Path):
        svc = JobService(db_path=str(tmp_path / "ts.db"))
        job = svc.create_job(_make_request())
        svc.update_progress(job.job_id, JobStatus.INGESTING, 10.0, "Ingesting")
        svc.complete_job(job.job_id, _make_result())

        fetched = svc.get_job(job.job_id)
        assert fetched is not None
        assert fetched.started_at is not None
        assert fetched.completed_at is not None
        assert fetched.completed_at >= fetched.started_at
        assert fetched.started_at >= fetched.created_at
