"""Unit tests for HardwareAccelerationService and device configuration."""

import os
from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.acceleration_service import (
    AccelerationConfig,
    AccelerationReport,
    DeviceMode,
    FFmpegEncoderMode,
    HardwareAccelerationService,
)


class TestAccelerationConfig:
    def test_default_config(self, monkeypatch):
        monkeypatch.delenv("ACCELERATION_DEVICE", raising=False)
        monkeypatch.delenv("WHISPER_DEVICE", raising=False)
        monkeypatch.delenv("WHISPER_COMPUTE_TYPE", raising=False)
        monkeypatch.delenv("FFMPEG_ACCELERATION", raising=False)

        config = AccelerationConfig.from_env()
        assert config.device_mode == DeviceMode.AUTO
        assert config.whisper_device == DeviceMode.AUTO
        assert config.whisper_compute_type == "auto"
        assert config.ffmpeg_encoder_mode == FFmpegEncoderMode.AUTO

    def test_custom_env_config(self, monkeypatch):
        monkeypatch.setenv("ACCELERATION_DEVICE", "cuda")
        monkeypatch.setenv("WHISPER_DEVICE", "cuda")
        monkeypatch.setenv("WHISPER_COMPUTE_TYPE", "float16")
        monkeypatch.setenv("FFMPEG_ACCELERATION", "nvenc")

        config = AccelerationConfig.from_env()
        assert config.device_mode == DeviceMode.CUDA
        assert config.whisper_device == DeviceMode.CUDA
        assert config.whisper_compute_type == "float16"
        assert config.ffmpeg_encoder_mode == FFmpegEncoderMode.NVENC

    def test_cpu_mode_env_config(self, monkeypatch):
        monkeypatch.setenv("ACCELERATION_DEVICE", "cpu")
        monkeypatch.setenv("WHISPER_DEVICE", "cpu")
        monkeypatch.setenv("WHISPER_COMPUTE_TYPE", "int8")
        monkeypatch.setenv("FFMPEG_ACCELERATION", "cpu")

        config = AccelerationConfig.from_env()
        assert config.device_mode == DeviceMode.CPU
        assert config.whisper_device == DeviceMode.CPU
        assert config.whisper_compute_type == "int8"
        assert config.ffmpeg_encoder_mode == FFmpegEncoderMode.CPU


class TestHardwareAccelerationService:
    def test_cuda_detection_via_ctranslate2(self, monkeypatch):
        import sys

        mock_ctranslate2 = MagicMock()
        mock_ctranslate2.get_cuda_device_count.return_value = 1
        monkeypatch.setitem(sys.modules, "ctranslate2", mock_ctranslate2)

        service = HardwareAccelerationService(config=AccelerationConfig(device_mode=DeviceMode.AUTO))
        assert service.is_cuda_available() is True
        assert service.get_cuda_device_count() == 1

    def test_cuda_detection_failure_gracefully_handled(self):
        service = HardwareAccelerationService(config=AccelerationConfig(device_mode=DeviceMode.AUTO))
        service._cuda_available_cache = False
        service._cuda_device_count_cache = 0
        service._cuda_device_names_cache = []

        assert service.is_cuda_available() is False
        assert service.get_cuda_device_count() == 0
        assert service.get_cuda_device_names() == []

    def test_nvenc_detection_success(self, monkeypatch):
        service = HardwareAccelerationService()
        mock_run = MagicMock(return_value=subprocess.CompletedProcess(args=["ffmpeg"], returncode=0, stdout=" V..... h264_nvenc NVIDIA NVENC H.264 encoder\n"))
        monkeypatch.setattr(subprocess, "run", mock_run)

        assert service.is_nvenc_available() is True

    def test_nvenc_detection_failure(self, monkeypatch):
        service = HardwareAccelerationService()
        mock_run = MagicMock(return_value=subprocess.CompletedProcess(args=["ffmpeg"], returncode=0, stdout=" V..... libx264 H.264 / AVC\n"))
        monkeypatch.setattr(subprocess, "run", mock_run)

        assert service.is_nvenc_available() is False

    def test_resolve_whisper_device_auto_with_cuda(self):
        service = HardwareAccelerationService(config=AccelerationConfig(device_mode=DeviceMode.AUTO))
        service._cuda_available_cache = True
        service._cuda_device_count_cache = 1

        dev, comp = service.resolve_whisper_device_and_compute_type()
        assert dev == "cuda"
        assert comp == "float16"

    def test_resolve_whisper_device_auto_without_cuda(self):
        service = HardwareAccelerationService(config=AccelerationConfig(device_mode=DeviceMode.AUTO))
        service._cuda_available_cache = False
        service._cuda_device_count_cache = 0

        dev, comp = service.resolve_whisper_device_and_compute_type()
        assert dev == "cpu"
        assert comp == "int8"

    def test_resolve_whisper_device_forced_cuda_missing_hardware_falls_back(self):
        service = HardwareAccelerationService(config=AccelerationConfig(device_mode=DeviceMode.CUDA, whisper_device=DeviceMode.CUDA))
        service._cuda_available_cache = False

        dev, comp = service.resolve_whisper_device_and_compute_type()
        assert dev == "cpu"
        assert comp == "int8"

    def test_get_video_encoder_flags(self):
        service = HardwareAccelerationService()
        nvenc_flags = service.get_video_encoder_flags(use_nvenc=True)
        assert "-c:v" in nvenc_flags
        assert nvenc_flags[nvenc_flags.index("-c:v") + 1] == "h264_nvenc"

        cpu_flags = service.get_video_encoder_flags(use_nvenc=False)
        assert "-c:v" in cpu_flags
        assert cpu_flags[cpu_flags.index("-c:v") + 1] == "libx264"

    def test_run_ffmpeg_with_fallback_nvenc_success(self, monkeypatch):
        service = HardwareAccelerationService(config=AccelerationConfig(ffmpeg_encoder_mode=FFmpegEncoderMode.NVENC))
        service._nvenc_available_cache = True
        service._cuda_available_cache = True

        called_cmds = []

        def mock_run(cmd, **kwargs):
            called_cmds.append(cmd)
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", mock_run)

        def cmd_builder(use_nvenc: bool):
            return ["ffmpeg", "-c:v", "h264_nvenc" if use_nvenc else "libx264", "out.mp4"]

        res = service.run_ffmpeg_with_fallback(cmd_builder)
        assert res.returncode == 0
        assert len(called_cmds) == 1
        assert "h264_nvenc" in called_cmds[0]

    def test_run_ffmpeg_with_fallback_nvenc_failure_retries_cpu(self, monkeypatch):
        service = HardwareAccelerationService(config=AccelerationConfig(ffmpeg_encoder_mode=FFmpegEncoderMode.NVENC))
        service._nvenc_available_cache = True
        service._cuda_available_cache = True

        called_cmds = []

        def mock_run(cmd, **kwargs):
            called_cmds.append(cmd)
            if "h264_nvenc" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="Error opening NVENC device")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", mock_run)

        def cmd_builder(use_nvenc: bool):
            return ["ffmpeg", "-c:v", "h264_nvenc" if use_nvenc else "libx264", "out.mp4"]

        res = service.run_ffmpeg_with_fallback(cmd_builder)
        assert res.returncode == 0
        assert len(called_cmds) == 2
        assert "h264_nvenc" in called_cmds[0]
        assert "libx264" in called_cmds[1]

    def test_acceleration_report(self):
        service = HardwareAccelerationService(config=AccelerationConfig(device_mode=DeviceMode.AUTO))
        service._cuda_available_cache = True
        service._cuda_device_count_cache = 1
        service._cuda_device_names_cache = ["NVIDIA GeForce RTX 4090"]
        service._nvenc_available_cache = True

        report = service.get_acceleration_report()
        assert isinstance(report, AccelerationReport)
        assert report.cuda_available is True
        assert report.cuda_device_count == 1
        assert report.cuda_device_names == ["NVIDIA GeForce RTX 4090"]
        assert report.nvenc_available is True
        assert report.effective_whisper_device == "cuda"
        assert report.effective_video_encoder == "h264_nvenc"


def test_api_system_acceleration_endpoint():
    client = TestClient(app)
    resp = client.get("/api/system/acceleration")
    assert resp.status_code == 200
    data = resp.json()
    assert "cuda_available" in data
    assert "cuda_device_count" in data
    assert "nvenc_available" in data
    assert "configured_device_mode" in data
    assert "effective_whisper_device" in data
    assert "effective_video_encoder" in data
