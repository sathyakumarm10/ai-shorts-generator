"""Integration and fallback tests for GPU-accelerated Whisper and FFmpeg NVENC."""

from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch
import pytest

from app.models import CaptionPreset, CaptionSegment, CaptionTrack, TimestampedTranscript, TranscriptSegment, VerticalVideoRequest, VideoClipRequest
from app.services.acceleration_service import AccelerationConfig, DeviceMode, FFmpegEncoderMode, HardwareAccelerationService
from app.services.caption_burn_service import CaptionBurnService
from app.services.media_tools_service import MediaToolsService
from app.services.transcription_service import FasterWhisperTranscriptionProvider, TranscriptionService
from app.services.vertical_video_service import VerticalVideoService
from app.services.video_clip_service import VideoClipService


class MockWhisperModelSuccess:
    def __init__(self, *args, **kwargs):
        self.device = kwargs.get("device", "cpu")
        self.compute_type = kwargs.get("compute_type", "int8")

    def transcribe(self, path, **kwargs):
        class Seg:
            start = 0.0
            end = 5.0
            text = "Accelerated transcription successful."

        return [Seg()], None


class MockWhisperModelFailsOnCuda:
    def __init__(self, *args, **kwargs):
        dev = kwargs.get("device", "cpu")
        if dev == "cuda":
            raise RuntimeError("CUDA out of memory or cuDNN library not found.")
        self.device = dev
        self.compute_type = kwargs.get("compute_type", "int8")

    def transcribe(self, path, **kwargs):
        class Seg:
            start = 0.0
            end = 5.0
            text = "CPU fallback transcription completed."

        return [Seg()], None


class MockWhisperModelRuntimeCudaCrash:
    def __init__(self, *args, **kwargs):
        self.device = kwargs.get("device", "cpu")
        self.compute_type = kwargs.get("compute_type", "int8")

    def transcribe(self, path, **kwargs):
        if self.device == "cuda":
            raise RuntimeError("CUDA device assert triggered during decode.")

        class Seg:
            start = 0.0
            end = 5.0
            text = "Recovered on CPU."

        return [Seg()], None


class TestWhisperGPUFallback:
    def test_whisper_cuda_load_failure_falls_back_to_cpu(self, monkeypatch, tmp_path: Path):
        test_audio = tmp_path / "audio.wav"
        test_audio.write_bytes(b"dummy wav data")

        accel = HardwareAccelerationService(config=AccelerationConfig(device_mode=DeviceMode.CUDA, whisper_device=DeviceMode.CUDA))
        accel._cuda_available_cache = True

        monkeypatch.setattr("faster_whisper.WhisperModel", MockWhisperModelFailsOnCuda)

        provider = FasterWhisperTranscriptionProvider(
            device="cuda",
            compute_type="float16",
            acceleration_service=accel,
            lazy_load=True,
        )

        transcript = provider.transcribe(test_audio)
        assert len(transcript.segments) == 1
        assert "CPU fallback" in transcript.segments[0].text
        assert provider.effective_device == "cpu"
        assert provider.effective_compute_type == "int8"

    def test_whisper_cuda_runtime_crash_falls_back_to_cpu(self, monkeypatch, tmp_path: Path):
        test_audio = tmp_path / "audio.wav"
        test_audio.write_bytes(b"dummy wav data")

        accel = HardwareAccelerationService(config=AccelerationConfig(device_mode=DeviceMode.CUDA, whisper_device=DeviceMode.CUDA))
        accel._cuda_available_cache = True

        monkeypatch.setattr("faster_whisper.WhisperModel", MockWhisperModelRuntimeCudaCrash)

        provider = FasterWhisperTranscriptionProvider(
            device="cuda",
            compute_type="float16",
            acceleration_service=accel,
            lazy_load=True,
        )

        transcript = provider.transcribe(test_audio)
        assert len(transcript.segments) == 1
        assert "Recovered on CPU" in transcript.segments[0].text
        assert provider.effective_device == "cpu"


class TestVideoClipServiceGPUFallback:
    def test_clip_service_nvenc_fails_and_recovers_on_cpu(self, monkeypatch, tmp_path: Path):
        input_vid = tmp_path / "source.mp4"
        input_vid.write_bytes(b"video content")
        out_dir = tmp_path / "clips"

        accel = HardwareAccelerationService(config=AccelerationConfig(ffmpeg_encoder_mode=FFmpegEncoderMode.NVENC))
        accel._nvenc_available_cache = True
        accel._cuda_available_cache = True

        execution_history = []

        def mock_run(cmd, **kwargs):
            execution_history.append(list(cmd))
            # Determine output file path from cmd (last item)
            out_file = Path(cmd[-1])
            if "h264_nvenc" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="NVENC initialization failed")
            # Successful CPU execution
            out_file.write_bytes(b"rendered mp4 bytes")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", mock_run)

        service = VideoClipService(output_dir=out_dir, acceleration_service=accel)
        clip = service.create_clip(input_vid, VideoClipRequest(start_seconds=10.0, duration_seconds=30.0))

        assert Path(clip.file_path).is_file()
        assert len(execution_history) == 2
        assert "h264_nvenc" in execution_history[0]
        assert "libx264" in execution_history[1]


class TestVerticalVideoServiceGPUFallback:
    def test_vertical_service_nvenc_fails_and_recovers_on_cpu(self, monkeypatch, tmp_path: Path):
        input_vid = tmp_path / "source.mp4"
        input_vid.write_bytes(b"video content")
        out_dir = tmp_path / "vertical"

        accel = HardwareAccelerationService(config=AccelerationConfig(ffmpeg_encoder_mode=FFmpegEncoderMode.NVENC))
        accel._nvenc_available_cache = True
        accel._cuda_available_cache = True

        execution_history = []

        def mock_run(cmd, **kwargs):
            execution_history.append(list(cmd))
            out_file = Path(cmd[-1])
            if "h264_nvenc" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="Device creation failed")
            out_file.write_bytes(b"rendered 9:16 vertical mp4 bytes")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", mock_run)

        service = VerticalVideoService(output_dir=out_dir, acceleration_service=accel, enable_smart_framing=False)
        result = service.convert_to_vertical(input_vid, VerticalVideoRequest(width=1080, height=1920))

        assert Path(result.file_path).is_file()
        assert len(execution_history) == 2
        assert "h264_nvenc" in execution_history[0]
        assert "libx264" in execution_history[1]


class TestCaptionBurnServiceGPUFallback:
    def test_caption_burn_service_nvenc_fails_and_recovers_on_cpu(self, monkeypatch, tmp_path: Path):
        input_vid = tmp_path / "vertical.mp4"
        input_vid.write_bytes(b"vertical video content")
        out_dir = tmp_path / "captioned"

        accel = HardwareAccelerationService(config=AccelerationConfig(ffmpeg_encoder_mode=FFmpegEncoderMode.NVENC))
        accel._nvenc_available_cache = True
        accel._cuda_available_cache = True

        execution_history = []

        def mock_run(cmd, **kwargs):
            execution_history.append(list(cmd))
            out_file = Path(cmd[-1])
            if "h264_nvenc" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="NVENC hardware error")
            out_file.write_bytes(b"captioned mp4 bytes")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", mock_run)

        service = CaptionBurnService(output_dir=out_dir, acceleration_service=accel)
        track = CaptionTrack(segments=[CaptionSegment(start_seconds=0.0, end_seconds=3.0, text="Hello world")])
        result = service.burn_captions(input_vid, track, preset=CaptionPreset.DEFAULT, enable_karaoke=False)

        assert Path(result.file_path).is_file()
        assert len(execution_history) == 2
        assert "h264_nvenc" in execution_history[0]
        assert "libx264" in execution_history[1]


class TestMediaToolsServiceAcceleration:
    def test_media_tools_includes_acceleration_report(self, monkeypatch):
        accel = HardwareAccelerationService(config=AccelerationConfig(device_mode=DeviceMode.AUTO))
        accel._cuda_available_cache = False
        accel._nvenc_available_cache = False

        service = MediaToolsService(acceleration_service=accel)
        report = service.check_all()

        assert report.acceleration is not None
        assert report.acceleration.cuda_available is False
        assert report.acceleration.effective_whisper_device == "cpu"
        assert report.acceleration.effective_video_encoder == "libx264"
