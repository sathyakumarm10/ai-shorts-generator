from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.models import (
    GeneratedHighlightClip,
    HighlightCandidate,
    HighlightMethod,
    HighlightScore,
    IngestedVideo,
    OutcomeStatus,
    ProcessingStage,
    ShortsGenerationRequest,
    TimestampedTranscript,
    TranscriptSegment,
    VideoMetadata,
    VideoSource,
    VideoSourceType,
)
from app.services.media_output_validation_service import (
    MediaOutputValidationError,
    MediaOutputValidationService,
)
from app.services.job_runner_service import JobRunnerService
from app.services.job_service import JobService
from app.services.media_storage_service import CloudSyncReport
from app.services.shorts_generation_service import ShortsGenerationError, ShortsGenerationService


def _candidate(start: float) -> HighlightCandidate:
    return HighlightCandidate(
        start_seconds=start,
        end_seconds=start + 30,
        duration_seconds=30,
        text=f"Highlight at {start}",
        score=HighlightScore(overall=.9, hook=.8, emotion=.8, curiosity=.8, information_density=.8),
    )


def _pipeline(*, candidate_count: int = 2):
    candidates = [_candidate(index * 35.0) for index in range(candidate_count)]
    ingestion = MagicMock()
    ingestion.ingest.return_value = IngestedVideo(file_path="source.mp4")
    metadata = MagicMock()
    metadata.extract_metadata.return_value = VideoMetadata(duration_seconds=120, width=1920, height=1080, format="mp4", file_size_bytes=10)
    transcription = MagicMock()
    transcription.transcribe.return_value = TimestampedTranscript(segments=[TranscriptSegment(start_seconds=0, end_seconds=100, text="Useful spoken content")])
    ai = MagicMock()
    ai.generate_ai_candidates.return_value = candidates
    heuristic = MagicMock()
    heuristic.generate_candidates.return_value = candidates
    clips = MagicMock()
    clips.generate_clips.return_value = [GeneratedHighlightClip(candidate=c, file_path=f"clip-{i}.mp4") for i, c in enumerate(candidates)]
    vertical = MagicMock()
    vertical.convert_to_vertical.side_effect = lambda path, request, output_filename=None: IngestedVideo(file_path=f"vertical-{path}")
    captions = MagicMock()
    captions.extract_short_captions.return_value = MagicMock()
    burn = MagicMock()
    burn.burn_captions.side_effect = lambda path, track, **kwargs: IngestedVideo(file_path=f"captioned-{path}")
    validator = MagicMock()
    service = ShortsGenerationService(
        ingestion_service=ingestion,
        metadata_service=metadata,
        transcription_service=transcription,
        ai_highlight_service=ai,
        highlight_scoring_service=heuristic,
        highlight_clip_service=clips,
        vertical_video_service=vertical,
        caption_service=captions,
        caption_burn_service=burn,
        output_validation_service=validator,
    )
    return service, {
        "candidates": candidates, "transcription": transcription, "ai": ai,
        "heuristic": heuristic, "clips": clips, "vertical": vertical,
        "burn": burn, "validator": validator,
    }


def _run(service, **kwargs):
    return service.generate(VideoSource(type=VideoSourceType.UPLOAD, location="source.mp4"), number_of_clips=2, **kwargs)


def test_all_stages_succeed():
    service, deps = _pipeline()
    result = _run(service, include_captions=False)
    assert result.completion_state == OutcomeStatus.SUCCESS
    assert len(result.generated_shorts) == 2
    assert all(item.status == OutcomeStatus.SUCCESS for item in result.clip_outcomes)
    assert result.highlight_method == HighlightMethod.REMOTE_AI


def test_one_vertical_clip_failure_is_recorded_and_success_remains():
    service, deps = _pipeline()
    deps["vertical"].convert_to_vertical.side_effect = [RuntimeError("encoder path C:\\private"), IngestedVideo(file_path="vertical-ok.mp4")]
    result = _run(service, include_captions=False)
    assert result.completion_state == OutcomeStatus.WARNING
    assert len(result.generated_shorts) == 1
    assert result.clip_outcomes[0].status == OutcomeStatus.FAILURE
    assert "private" not in result.clip_outcomes[0].message


def test_all_vertical_clips_fail_job():
    service, deps = _pipeline()
    deps["vertical"].convert_to_vertical.side_effect = RuntimeError("gpu failure")
    with pytest.raises(ShortsGenerationError, match="All candidate short rendering attempts failed"):
        _run(service, include_captions=False)


def test_caption_failure_keeps_valid_uncaptioned_clip_with_warning():
    service, deps = _pipeline(candidate_count=1)
    deps["burn"].burn_captions.side_effect = RuntimeError("C:\\secret\\font.ass API_KEY=hidden")
    result = service.generate(VideoSource(type=VideoSourceType.UPLOAD, location="source.mp4"), number_of_clips=1)
    short = result.generated_shorts[0]
    assert short.captions_present is False
    assert short.final_file_path == short.vertical_clip_path
    assert result.completion_state == OutcomeStatus.WARNING
    assert "secret" not in " ".join(result.warnings)


def test_transcription_exception_and_empty_transcript_fail():
    service, deps = _pipeline()
    deps["transcription"].transcribe.side_effect = RuntimeError("model internals")
    with pytest.raises(ShortsGenerationError, match="No usable speech"):
        _run(service)

    service, deps = _pipeline()
    deps["transcription"].transcribe.return_value = TimestampedTranscript(segments=[])
    with pytest.raises(ShortsGenerationError, match="No usable speech"):
        _run(service)


def test_ai_failure_uses_reported_heuristic_fallback():
    service, deps = _pipeline()
    deps["ai"].generate_ai_candidates.side_effect = RuntimeError("provider secret")
    result = _run(service, include_captions=False)
    assert result.highlight_method == HighlightMethod.HEURISTIC_FALLBACK
    assert result.completion_state == OutcomeStatus.WARNING
    assert any(item.stage == ProcessingStage.HIGHLIGHT_SELECTION and item.status == OutcomeStatus.WARNING for item in result.stage_outcomes)


def test_ai_and_heuristic_failure_fails_job():
    service, deps = _pipeline()
    deps["ai"].generate_ai_candidates.side_effect = RuntimeError("provider failed")
    deps["heuristic"].generate_candidates.side_effect = RuntimeError("heuristic failed")
    with pytest.raises(ShortsGenerationError, match="No highlight clips could be selected"):
        _run(service)


def test_invalid_generated_output_fails_clip():
    service, deps = _pipeline(candidate_count=1)
    deps["validator"].validate_video.side_effect = MediaOutputValidationError("Generated video failed media validation.")
    with pytest.raises(ShortsGenerationError, match="All candidate short rendering attempts failed"):
        service.generate(VideoSource(type=VideoSourceType.UPLOAD, location="source.mp4"), number_of_clips=1, include_captions=False)


def test_output_validator_checks_probe_duration_and_dimensions(tmp_path: Path):
    output = tmp_path / "valid.mp4"
    output.write_bytes(b"video")
    metadata = MagicMock()
    metadata.extract_metadata.return_value = VideoMetadata(duration_seconds=30, width=1080, height=1920, format="mp4", file_size_bytes=5)
    validator = MediaOutputValidationService(metadata_service=metadata)
    assert validator.validate_video(output, expected_duration_seconds=30, expected_width=1080, expected_height=1920).height == 1920
    metadata.extract_metadata.return_value = VideoMetadata(duration_seconds=12, width=1080, height=1920, format="mp4", file_size_bytes=5)
    with pytest.raises(MediaOutputValidationError, match="duration"):
        validator.validate_video(output, expected_duration_seconds=30)


def _runner_request():
    return ShortsGenerationRequest(
        source=VideoSource(type=VideoSourceType.YOUTUBE, location="https://www.youtube.com/watch?v=test"),
        number_of_clips=1,
    )


def test_optional_cloud_sync_failure_completes_with_warning():
    pipeline, _ = _pipeline(candidate_count=1)
    result = pipeline.generate(
        VideoSource(type=VideoSourceType.UPLOAD, location="source.mp4"),
        number_of_clips=1,
        include_captions=False,
    )
    shorts = MagicMock()
    shorts.generate.return_value = result
    media = MagicMock()
    media.sync_job_to_cloud.return_value = CloudSyncReport(attempted=True, required=False, failure_count=1)
    media.normalize_result_paths.side_effect = lambda value: value
    jobs = JobService()
    request = _runner_request()
    job = jobs.create_job(request)
    runner = JobRunnerService(job_service=jobs, shorts_service=shorts, media_storage=media)
    runner.execute_job_pipeline(job.job_id, request)
    stored = jobs.get_job(job.job_id)
    assert stored.status.value == "completed"
    assert stored.result.completion_state == OutcomeStatus.WARNING
    assert any(outcome.stage == ProcessingStage.STORAGE_SYNC for outcome in stored.result.stage_outcomes)
    runner.shutdown()


def test_job_user_error_does_not_expose_diagnostic_path_or_secret():
    shorts = MagicMock()
    shorts.generate.side_effect = ShortsGenerationError(
        "Caption rendering failed.",
        diagnostic="C:\\private\\render.ass API_KEY=top-secret",
        stage=ProcessingStage.CAPTIONS,
    )
    media = MagicMock()
    jobs = JobService()
    request = _runner_request()
    job = jobs.create_job(request)
    runner = JobRunnerService(job_service=jobs, shorts_service=shorts, media_storage=media)
    with pytest.raises(ShortsGenerationError):
        runner.execute_job_pipeline(job.job_id, request)
    stored = jobs.get_job(job.job_id)
    assert stored.error == "Caption rendering failed."
    assert "private" not in stored.error
    assert "top-secret" not in stored.error
    runner.shutdown()
