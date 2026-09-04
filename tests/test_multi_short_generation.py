"""Comprehensive test suite for Phase 9 Multi-Short Generation (up to 15 Shorts per source video).

Covers:
- Request validation for number_of_clips (1 <= number_of_clips <= 15)
- Smart candidate deduplication (IoU <= 0.35, min start distance >= 10s)
- Rank ordering preservation by highlight score
- Rendering all candidates up to requested count with sequential indexes
  (clip_001.mp4, short_001.mp4)
- Fault-tolerant rendering (individual short failure does not abort remaining shorts)
- Subtitle extraction, timestamp offsetting, line splitting, and burn-in
- API endpoint and JobRecord persistence of complete multi-short results
- SQLite and PostgreSQL store multi-short serialization and relative path preservation
- Worker execution (Redis queue & ThreadPool fallback)
- Hardware acceleration GPU NVENC compatibility and CPU fallback
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.models import (
    CaptionPreset,
    CaptionSegment,
    CaptionTrack,
    FramingType,
    GeneratedHighlightClip,
    GeneratedShort,
    HighlightCandidate,
    HighlightScore,
    HighlightSource,
    IngestedVideo,
    JobRecord,
    JobStatus,
    ShortsGenerationRequest,
    ShortsGenerationResult,
    TimestampedTranscript,
    TranscriptSegment,
    VerticalVideoRequest,
    VideoJobRequest,
    VideoMetadata,
    VideoSource,
    VideoSourceType,
)
from app.services.caption_service import CaptionService
from app.services.acceleration_service import (
    AccelerationConfig,
    FFmpegEncoderMode,
    HardwareAccelerationService,
)
from app.services.highlight_clip_service import HighlightClipService
from app.services.highlight_scoring_service import HighlightScoringService
from app.services.job_postgres import _job_to_params, _row_to_job
from app.services.job_runner_service import JobRunnerService
from app.services.job_service import JobService
from app.services.job_sqlite import SQLiteJobStore
from app.services.media_storage_service import MediaStorageService
from app.services.queue_service import RedisJobQueue
from app.services.shorts_generation_service import (
    ShortsGenerationError,
    ShortsGenerationService,
)
from app.services.vertical_video_service import VerticalVideoService


@pytest.fixture
def test_client():
    return TestClient(app)


def _make_transcript_with_segments(num_segments=30, segment_duration=10.0):
    segments = []
    for i in range(num_segments):
        start = i * segment_duration
        end = (i + 1) * segment_duration
        text = (
            f"Segment number {i+1} discussing incredible viral breakthrough "
            "concepts in technology."
        )
        segments.append(TranscriptSegment(start_seconds=start, end_seconds=end, text=text))
    return TimestampedTranscript(segments=segments)


# ==============================================================================
# 1. Request Validation Tests
# ==============================================================================


class TestRequestValidation:
    def test_default_number_of_clips_is_10(self):
        req = ShortsGenerationRequest(
            source=VideoSource(type=VideoSourceType.UPLOAD, location="test.mp4")
        )
        assert req.number_of_clips == 10

    def test_valid_number_of_clips_range(self):
        for count in (1, 5, 10, 15):
            req = ShortsGenerationRequest(
                source=VideoSource(type=VideoSourceType.UPLOAD, location="test.mp4"),
                number_of_clips=count,
            )
            assert req.number_of_clips == count

    def test_reject_number_of_clips_greater_than_15(self):
        with pytest.raises(ValueError, match="number_of_clips must be between 1 and 15"):
            ShortsGenerationRequest.model_validate(
                {
                    "source": {"type": "upload", "location": "test.mp4"},
                    "number_of_clips": 16,
                }
            )

    def test_reject_number_of_clips_less_than_1(self):
        with pytest.raises(ValueError):
            ShortsGenerationRequest.model_validate(
                {
                    "source": {"type": "upload", "location": "test.mp4"},
                    "number_of_clips": 0,
                }
            )

    def test_video_job_request_number_of_clips_validation(self):
        v_req = VideoJobRequest(
            source=VideoSource(type=VideoSourceType.UPLOAD, location="test.mp4"),
            clip_duration=60,
            number_of_clips=15,
        )
        assert v_req.number_of_clips == 15

        with pytest.raises(ValueError):
            VideoJobRequest.model_validate(
                {
                    "source": {"type": "upload", "location": "test.mp4"},
                    "clip_duration": 60,
                    "number_of_clips": 20,
                }
            )


# ==============================================================================
# 2. Candidate Selection & Deduplication Tests
# ==============================================================================


class TestCandidateDeduplicationAndRanking:
    def test_candidate_iou_deduplication(self):
        service = HighlightScoringService()
        transcript = _make_transcript_with_segments(
            num_segments=50, segment_duration=10.0
        )

        candidates = service.generate_candidates(
            transcript=transcript,
            min_duration=30.0,
            max_duration=60.0,
            target_duration=40.0,
            allow_overlap=False,
        )

        assert len(candidates) >= 2
        for i in range(len(candidates)):
            for j in range(i + 1, len(candidates)):
                c1, c2 = candidates[i], candidates[j]
                inter = max(
                    0.0,
                    min(c1.end_seconds, c2.end_seconds)
                    - max(c1.start_seconds, c2.start_seconds),
                )
                union = max(
                    1e-6,
                    max(c1.end_seconds, c2.end_seconds)
                    - min(c1.start_seconds, c2.start_seconds),
                )
                iou = inter / union
                assert iou <= 0.35 + 1e-4, f"Candidates {i} & {j} IoU {iou:.3f} > 0.35"

    def test_candidate_minimum_start_distance_filtering(self):
        service = HighlightScoringService()
        transcript = _make_transcript_with_segments(
            num_segments=50, segment_duration=10.0
        )
        candidates = service.generate_candidates(transcript=transcript)

        assert len(candidates) >= 2
        for i in range(len(candidates)):
            for j in range(i + 1, len(candidates)):
                dist = abs(candidates[i].start_seconds - candidates[j].start_seconds)
                assert dist >= 10.0 - 1e-4, f"Start distance {dist}s below 10.0s"

    def test_candidate_ranking_by_score(self):
        service = HighlightScoringService()
        transcript = _make_transcript_with_segments(
            num_segments=40, segment_duration=10.0
        )
        candidates = service.generate_candidates(transcript=transcript)

        for i in range(len(candidates) - 1):
            assert candidates[i].score.overall >= candidates[i + 1].score.overall

    def test_insufficient_candidate_handling(self):
        service = HighlightScoringService()
        short_transcript = _make_transcript_with_segments(
            num_segments=6, segment_duration=10.0
        )
        candidates = service.generate_candidates(
            short_transcript, min_duration=30.0, max_duration=60.0
        )

        assert len(candidates) <= 2
        coords = {(c.start_seconds, c.end_seconds) for c in candidates}
        assert len(candidates) == len(coords)


# ==============================================================================
# 3. Multi-Short Orchestration & Deterministic Naming Tests
# ==============================================================================


class TestMultiShortGenerationService:
    def test_multi_short_pipeline_generates_up_to_requested_count(self):
        mock_ingestion = MagicMock()
        mock_ingested = IngestedVideo(file_path="downloads/uploads/source.mp4")
        mock_ingestion.ingest.return_value = mock_ingested

        mock_metadata = MagicMock()
        mock_metadata.extract_metadata.return_value = VideoMetadata(
            duration_seconds=300.0,
            width=1920,
            height=1080,
            format="mp4",
            file_size_bytes=1048576,
        )

        mock_transcription = MagicMock()
        mock_transcript = _make_transcript_with_segments(
            num_segments=30, segment_duration=10.0
        )
        mock_transcription.transcribe.return_value = mock_transcript

        mock_scoring = MagicMock()
        fake_candidates = [
            HighlightCandidate(
                start_seconds=float(i * 20),
                end_seconds=float(i * 20 + 30),
                duration_seconds=30.0,
                text=f"Clip text {i+1}",
                score=HighlightScore(
                    overall=0.9 - (i * 0.02),
                    hook=0.8,
                    emotion=0.8,
                    curiosity=0.8,
                    information_density=0.8,
                ),
            )
            for i in range(10)
        ]
        mock_scoring.generate_candidates.return_value = fake_candidates

        mock_clip_svc = MagicMock()
        rendered_clips = [
            GeneratedHighlightClip(
                candidate=cand, file_path=f"outputs/clips/clip_{i+1:03d}.mp4"
            )
            for i, cand in enumerate(fake_candidates)
        ]
        mock_clip_svc.generate_clips.return_value = rendered_clips

        mock_vert_svc = MagicMock()
        mock_vert_svc.convert_to_vertical.side_effect = (
            lambda path, req, output_filename=None: IngestedVideo(
                file_path=f"outputs/vertical/{output_filename or 'short.mp4'}"
            )
        )

        mock_caption_burn = MagicMock()
        mock_caption_burn.burn_captions.side_effect = (
            lambda path, track, **kwargs: IngestedVideo(
                file_path=f"outputs/captioned/{kwargs.get('output_filename') or 'captioned.mp4'}"
            )
        )

        service = ShortsGenerationService(
            ingestion_service=mock_ingestion,
            metadata_service=mock_metadata,
            transcription_service=mock_transcription,
            highlight_scoring_service=mock_scoring,
            highlight_clip_service=mock_clip_svc,
            vertical_video_service=mock_vert_svc,
            caption_burn_service=mock_caption_burn,
        )

        request = ShortsGenerationRequest(
            source=VideoSource(
                type=VideoSourceType.UPLOAD,
                location="downloads/uploads/source.mp4",
            ),
            number_of_clips=10,
        )

        result = service.generate(request)

        assert len(result.generated_shorts) == 10
        for i, short in enumerate(result.generated_shorts, start=1):
            assert short.index == i
            assert short.source_clip_path == f"outputs/clips/clip_{i:03d}.mp4"
            assert short.vertical_clip_path == f"outputs/vertical/short_{i:03d}.mp4"
            assert short.captioned_clip_path == f"outputs/captioned/short_{i:03d}.mp4"
            assert short.final_file_path == f"outputs/captioned/short_{i:03d}.mp4"
            assert short.caption_track is not None

    def test_individual_candidate_failure_continues_remaining_shorts(self):
        mock_ingestion = MagicMock()
        mock_ingested = IngestedVideo(file_path="source.mp4")
        mock_ingestion.ingest.return_value = mock_ingested

        mock_metadata = MagicMock()
        mock_metadata.extract_metadata.return_value = VideoMetadata(
            duration_seconds=300.0,
            width=1920,
            height=1080,
            format="mp4",
            file_size_bytes=1048576,
        )

        mock_transcription = MagicMock()
        mock_transcription.transcribe.return_value = _make_transcript_with_segments()

        mock_scoring = MagicMock()
        score_val = HighlightScore(
            overall=0.95,
            hook=0.8,
            emotion=0.8,
            curiosity=0.8,
            information_density=0.8,
        )
        fake_candidates = [
            HighlightCandidate(
                start_seconds=0.0,
                end_seconds=30.0,
                duration_seconds=30.0,
                text="Clip 1",
                score=score_val,
            ),
            HighlightCandidate(
                start_seconds=35.0,
                end_seconds=65.0,
                duration_seconds=30.0,
                text="Clip 2",
                score=score_val,
            ),
            HighlightCandidate(
                start_seconds=70.0,
                end_seconds=100.0,
                duration_seconds=30.0,
                text="Clip 3",
                score=score_val,
            ),
        ]
        mock_scoring.generate_candidates.return_value = fake_candidates

        mock_clip_svc = MagicMock()
        mock_clip_svc.generate_clips.return_value = [
            GeneratedHighlightClip(candidate=fake_candidates[0], file_path="clip_001.mp4"),
            GeneratedHighlightClip(candidate=fake_candidates[1], file_path="clip_002.mp4"),
            GeneratedHighlightClip(candidate=fake_candidates[2], file_path="clip_003.mp4"),
        ]

        mock_vert_svc = MagicMock()

        def mock_vert(path, req, output_filename=None):
            if "clip_002.mp4" in path:
                raise RuntimeError("Vertical FFmpeg encoder error on clip 2")
            return IngestedVideo(file_path=f"vertical/{output_filename}")

        mock_vert_svc.convert_to_vertical.side_effect = mock_vert

        mock_caption_burn = MagicMock()
        mock_caption_burn.burn_captions.side_effect = (
            lambda path, track, **kwargs: IngestedVideo(
                file_path=f"captioned/{kwargs.get('output_filename')}"
            )
        )

        service = ShortsGenerationService(
            ingestion_service=mock_ingestion,
            metadata_service=mock_metadata,
            transcription_service=mock_transcription,
            highlight_scoring_service=mock_scoring,
            highlight_clip_service=mock_clip_svc,
            vertical_video_service=mock_vert_svc,
            caption_burn_service=mock_caption_burn,
        )

        result = service.generate(
            VideoSource(type=VideoSourceType.UPLOAD, location="source.mp4"),
            number_of_clips=3,
        )

        assert len(result.generated_shorts) == 2
        assert result.generated_shorts[0].index == 1
        assert result.generated_shorts[1].index == 2
        assert result.generated_shorts[0].candidate.text == "Clip 1"
        assert result.generated_shorts[1].candidate.text == "Clip 3"

    def test_total_failure_raises_shorts_generation_error(self):
        mock_ingestion = MagicMock()
        mock_ingested = IngestedVideo(file_path="source.mp4")
        mock_ingestion.ingest.return_value = mock_ingested

        mock_metadata = MagicMock()
        mock_metadata.extract_metadata.return_value = VideoMetadata(
            duration_seconds=300.0,
            width=1920,
            height=1080,
            format="mp4",
            file_size_bytes=1048576,
        )

        mock_transcription = MagicMock()
        mock_transcription.transcribe.return_value = _make_transcript_with_segments()

        mock_scoring = MagicMock()
        score_val = HighlightScore(
            overall=0.95,
            hook=0.8,
            emotion=0.8,
            curiosity=0.8,
            information_density=0.8,
        )
        candidate = HighlightCandidate(
            start_seconds=0.0,
            end_seconds=30.0,
            duration_seconds=30.0,
            text="Clip 1",
            score=score_val,
        )
        mock_scoring.generate_candidates.return_value = [candidate]

        mock_clip_svc = MagicMock()
        mock_clip_svc.generate_clips.return_value = [
            GeneratedHighlightClip(candidate=candidate, file_path="clip_001.mp4")
        ]

        mock_vert_svc = MagicMock()
        mock_vert_svc.convert_to_vertical.side_effect = RuntimeError("Fatal GPU crash")

        service = ShortsGenerationService(
            ingestion_service=mock_ingestion,
            metadata_service=mock_metadata,
            transcription_service=mock_transcription,
            highlight_scoring_service=mock_scoring,
            highlight_clip_service=mock_clip_svc,
            vertical_video_service=mock_vert_svc,
        )

        with pytest.raises(ShortsGenerationError, match="All candidate short rendering attempts failed"):
            service.generate(
                VideoSource(type=VideoSourceType.UPLOAD, location="source.mp4"),
                number_of_clips=1,
            )


# ==============================================================================
# 4. Short Subtitles & Formatting Tests
# ==============================================================================


class TestShortSubtitles:
    def test_extract_short_captions_offsets_and_clamps_timestamps(self):
        svc = CaptionService()
        transcript = TimestampedTranscript(
            segments=[
                TranscriptSegment(start_seconds=10.0, end_seconds=15.0, text="Intro segment."),
                TranscriptSegment(start_seconds=15.5, end_seconds=22.0, text="Core explanation."),
                TranscriptSegment(start_seconds=23.0, end_seconds=35.0, text="Out of bounds."),
            ]
        )

        track = svc.extract_short_captions(
            transcript=transcript,
            start_seconds=12.0,
            end_seconds=20.0,
        )

        assert len(track.segments) >= 2
        assert track.segments[0].start_seconds >= 0.0
        assert track.segments[-1].end_seconds <= 8.0  # 20.0 - 12.0
        assert track.segments[0].text == "Intro segment."
        assert track.segments[1].text == "Core explanation."

    def test_extract_short_captions_splits_long_lines(self):
        svc = CaptionService()
        long_text = (
            "This is an exceptionally long caption sentence that definitely exceeds "
            "the 38 character limit for vertical mobile screens."
        )
        transcript = TimestampedTranscript(
            segments=[TranscriptSegment(start_seconds=5.0, end_seconds=15.0, text=long_text)]
        )

        track = svc.extract_short_captions(
            transcript=transcript,
            start_seconds=5.0,
            end_seconds=15.0,
            max_chars_per_line=38,
        )

        assert len(track.segments) > 1
        for seg in track.segments:
            assert len(seg.text) <= 38

    def test_extract_short_captions_non_overlapping_and_sequential(self):
        svc = CaptionService()
        transcript = _make_transcript_with_segments(num_segments=20, segment_duration=5.0)

        track = svc.extract_short_captions(
            transcript=transcript,
            start_seconds=10.0,
            end_seconds=40.0,
        )

        for i in range(len(track.segments) - 1):
            assert track.segments[i].end_seconds <= track.segments[i + 1].start_seconds + 1e-6


# ==============================================================================
# 5. Persistence & Relative Paths Tests
# ==============================================================================


class TestRelativePathAndPersistence:
    def test_media_storage_normalize_result_paths(self):
        media_svc = MediaStorageService(media_root="outputs")
        score_val = HighlightScore(
            overall=0.92,
            hook=0.8,
            emotion=0.8,
            curiosity=0.8,
            information_density=0.8,
        )
        short = GeneratedShort(
            index=1,
            candidate=HighlightCandidate(
                start_seconds=0.0,
                end_seconds=30.0,
                duration_seconds=30.0,
                text="Text",
                score=score_val,
            ),
            source_clip_path="C:/project/outputs/jobs/job-1/clips/clip_001.mp4",
            vertical_clip_path="C:/project/outputs/jobs/job-1/vertical/short_001.mp4",
            captioned_clip_path="C:/project/outputs/jobs/job-1/captioned/short_001.mp4",
            final_file_path="C:/project/outputs/jobs/job-1/captioned/short_001.mp4",
        )

        raw_result = ShortsGenerationResult(
            source_video=IngestedVideo(
                file_path="C:/project/outputs/jobs/job-1/source/video.mp4"
            ),
            metadata=VideoMetadata(
                duration_seconds=60.0,
                width=1920,
                height=1080,
                format="mp4",
                file_size_bytes=1048576,
            ),
            transcript=_make_transcript_with_segments(),
            candidates=[],
            generated_shorts=[short],
        )

        norm = media_svc.normalize_result_paths(raw_result)
        assert norm.source_video.file_path == "jobs/job-1/source/video.mp4"
        assert norm.generated_shorts[0].source_clip_path == "jobs/job-1/clips/clip_001.mp4"
        assert norm.generated_shorts[0].vertical_clip_path == "jobs/job-1/vertical/short_001.mp4"
        assert norm.generated_shorts[0].final_file_path == "jobs/job-1/captioned/short_001.mp4"

    def test_sqlite_persistence_multi_shorts_and_caption_track(self):
        store = SQLiteJobStore(":memory:")
        now = datetime.now(timezone.utc)
        score_val = HighlightScore(
            overall=0.92,
            hook=0.8,
            emotion=0.8,
            curiosity=0.8,
            information_density=0.8,
        )
        caption_track = CaptionTrack(
            segments=[
                CaptionSegment(start_seconds=0.0, end_seconds=2.0, text="Intro"),
                CaptionSegment(start_seconds=2.1, end_seconds=5.0, text="Next"),
            ]
        )
        shorts = [
            GeneratedShort(
                index=i,
                candidate=HighlightCandidate(
                    start_seconds=i * 20.0,
                    end_seconds=i * 20.0 + 30.0,
                    duration_seconds=30.0,
                    text=f"Text {i}",
                    score=score_val,
                ),
                source_clip_path=f"jobs/job-1/clips/clip_{i:03d}.mp4",
                vertical_clip_path=f"jobs/job-1/vertical/short_{i:03d}.mp4",
                final_file_path=f"jobs/job-1/captioned/short_{i:03d}.mp4",
                caption_track=caption_track,
            )
            for i in range(1, 11)
        ]

        result = ShortsGenerationResult(
            source_video=IngestedVideo(file_path="jobs/job-1/source/video.mp4"),
            metadata=VideoMetadata(
                duration_seconds=300.0,
                width=1920,
                height=1080,
                format="mp4",
                file_size_bytes=1048576,
            ),
            transcript=_make_transcript_with_segments(),
            candidates=[],
            generated_shorts=shorts,
        )

        job = JobRecord(
            job_id="job-multi-123",
            status=JobStatus.COMPLETED,
            progress_percent=100.0,
            message="Completed",
            created_at=now,
            started_at=now,
            completed_at=now,
            result=result,
        )

        store.insert(job)
        loaded = store.get("job-multi-123")

        assert loaded is not None
        assert loaded.result is not None
        assert len(loaded.result.generated_shorts) == 10
        for i, s in enumerate(loaded.result.generated_shorts, start=1):
            assert s.index == i
            assert s.final_file_path == f"jobs/job-1/captioned/short_{i:03d}.mp4"
            assert s.caption_track is not None
            assert len(s.caption_track.segments) == 2

    def test_postgres_persistence_multi_shorts_and_caption_track(self):
        now = datetime.now(timezone.utc)
        score_val = HighlightScore(
            overall=0.92,
            hook=0.8,
            emotion=0.8,
            curiosity=0.8,
            information_density=0.8,
        )
        caption_track = CaptionTrack(
            segments=[CaptionSegment(start_seconds=0.0, end_seconds=3.0, text="Hello")]
        )
        shorts = [
            GeneratedShort(
                index=i,
                candidate=HighlightCandidate(
                    start_seconds=float(i * 10),
                    end_seconds=float(i * 10 + 20),
                    duration_seconds=20.0,
                    text=f"Short {i}",
                    score=score_val,
                ),
                source_clip_path=f"jobs/pg-1/clips/clip_{i:03d}.mp4",
                vertical_clip_path=f"jobs/pg-1/vertical/short_{i:03d}.mp4",
                final_file_path=f"jobs/pg-1/captioned/short_{i:03d}.mp4",
                caption_track=caption_track,
            )
            for i in range(1, 4)
        ]
        result = ShortsGenerationResult(
            source_video=IngestedVideo(file_path="jobs/pg-1/source/video.mp4"),
            metadata=VideoMetadata(
                duration_seconds=60.0,
                width=1920,
                height=1080,
                format="mp4",
                file_size_bytes=1048576,
            ),
            transcript=_make_transcript_with_segments(),
            candidates=[],
            generated_shorts=shorts,
        )
        job = JobRecord(
            job_id="job-pg-test",
            status=JobStatus.COMPLETED,
            progress_percent=100.0,
            message="Completed",
            created_at=now,
            started_at=now,
            completed_at=now,
            result=result,
        )

        params = _job_to_params(job)
        row_dict = {
            "job_id": params[0],
            "status": params[1],
            "progress_percent": params[2],
            "message": params[3],
            "created_at": params[4],
            "started_at": params[5],
            "completed_at": params[6],
            "error": params[7],
            "result_json": params[8],
            "source_json": params[9],
            "clip_duration": params[10],
            "number_of_clips": params[11],
            "user_id": params[12],
            "retry_count": params[13],
            "queue_name": params[14],
        }

        reconstructed = _row_to_job(row_dict)
        assert reconstructed.result is not None
        assert len(reconstructed.result.generated_shorts) == 3
        assert reconstructed.result.generated_shorts[0].caption_track is not None
        assert reconstructed.result.generated_shorts[0].caption_track.segments[0].text == "Hello"

    def test_api_jobs_endpoint_returns_all_generated_shorts(self, test_client):
        from app.services.job_service import default_job_service

        now = datetime.now(timezone.utc)
        score_val = HighlightScore(
            overall=0.95,
            hook=0.8,
            emotion=0.8,
            curiosity=0.8,
            information_density=0.8,
        )
        job_id = f"job-api-{uuid4().hex[:8]}"
        shorts = [
            GeneratedShort(
                index=i,
                candidate=HighlightCandidate(
                    start_seconds=0.0,
                    end_seconds=30.0,
                    duration_seconds=30.0,
                    text=f"Clip {i}",
                    score=score_val,
                ),
                source_clip_path=f"jobs/{job_id}/clips/clip_{i:03d}.mp4",
                vertical_clip_path=f"jobs/{job_id}/vertical/short_{i:03d}.mp4",
                final_file_path=f"jobs/{job_id}/captioned/short_{i:03d}.mp4",
            )
            for i in range(1, 6)
        ]

        job = JobRecord(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            progress_percent=100.0,
            message="Done",
            created_at=now,
            started_at=now,
            completed_at=now,
            result=ShortsGenerationResult(
                source_video=IngestedVideo(file_path="source.mp4"),
                metadata=VideoMetadata(
                    duration_seconds=120.0,
                    width=1920,
                    height=1080,
                    format="mp4",
                    file_size_bytes=1048576,
                ),
                transcript=_make_transcript_with_segments(),
                candidates=[],
                generated_shorts=shorts,
            ),
        )

        default_job_service._store.insert(job)

        response = test_client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        data = response.json()

        assert data["job_id"] == job_id
        assert len(data["result"]["generated_shorts"]) == 5
        for i, s in enumerate(data["result"]["generated_shorts"], start=1):
            assert s["index"] == i
            assert s["final_file_path"] == f"jobs/{job_id}/captioned/short_{i:03d}.mp4"


# ==============================================================================
# 6. Worker Execution Tests
# ==============================================================================


class TestWorkerExecution:
    def test_redis_worker_job_submission(self):
        mock_queue = MagicMock(spec=RedisJobQueue)
        runner = JobRunnerService(queue=mock_queue)

        req = ShortsGenerationRequest(
            source=VideoSource(type=VideoSourceType.UPLOAD, location="test.mp4"),
            number_of_clips=5,
        )

        fut = runner.submit_job("job-redis-test", req)
        assert fut.done()
        mock_queue.enqueue.assert_called_once()
        args = mock_queue.enqueue.call_args[0]
        assert args[0] == "job-redis-test"
        assert args[1]["number_of_clips"] == 5

    def test_threadpool_worker_job_submission(self):
        runner = JobRunnerService()
        with patch.object(runner, "_execute_job_pipeline") as mock_exec:
            req = ShortsGenerationRequest(
                source=VideoSource(type=VideoSourceType.UPLOAD, location="test.mp4"),
                number_of_clips=5,
            )
            fut = runner.submit_job("job-tp-test", req)
            fut.result(timeout=5.0)
            mock_exec.assert_called_once_with("job-tp-test", req)


# ==============================================================================
# 7. Hardware Fallback Tests
# ==============================================================================


class TestHardwareFallback:
    def test_vertical_video_gpu_compatibility_and_cpu_fallback(
        self, monkeypatch, tmp_path: Path
    ):
        input_vid = tmp_path / "source.mp4"
        input_vid.write_bytes(b"dummy video")
        out_dir = tmp_path / "vertical"

        accel = HardwareAccelerationService(
            config=AccelerationConfig(ffmpeg_encoder_mode=FFmpegEncoderMode.NVENC)
        )
        accel._nvenc_available_cache = True
        accel._cuda_available_cache = True

        execution_history = []

        def mock_run(cmd, **kwargs):
            execution_history.append(list(cmd))
            out_file = Path(cmd[-1])
            if "h264_nvenc" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=1, stdout="", stderr="Device creation failed"
                )
            out_file.write_bytes(b"rendered 9:16 vertical mp4")
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="", stderr=""
            )

        monkeypatch.setattr(subprocess, "run", mock_run)

        service = VerticalVideoService(
            output_dir=out_dir,
            acceleration_service=accel,
            enable_smart_framing=False,
        )
        result = service.convert_to_vertical(
            input_vid, VerticalVideoRequest(width=1080, height=1920)
        )

        assert Path(result.file_path).is_file()
        assert len(execution_history) == 2
        assert "h264_nvenc" in execution_history[0]
        assert "libx264" in execution_history[1]
