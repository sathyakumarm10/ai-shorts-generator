"""Hardware acceleration and device orchestration service.

This module provides the `HardwareAccelerationService` for detecting NVIDIA CUDA GPU
capabilities, verifying FFmpeg NVENC hardware encoders, configuring CPU/GPU execution
modes, and orchestrating transparent automatic fallback to CPU processing when GPU
acceleration is unavailable or fails at runtime.
"""

from dataclasses import dataclass, field
from enum import Enum
import logging
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class DeviceMode(str, Enum):
    """Device mode configuration options."""

    AUTO = "auto"
    CUDA = "cuda"
    CPU = "cpu"


class FFmpegEncoderMode(str, Enum):
    """FFmpeg video encoder configuration options."""

    AUTO = "auto"
    NVENC = "nvenc"
    CPU = "cpu"


@dataclass
class AccelerationConfig:
    """Hardware acceleration configuration loaded from environment variables."""

    device_mode: DeviceMode = DeviceMode.AUTO
    whisper_device: DeviceMode = DeviceMode.AUTO
    whisper_compute_type: str = "auto"
    ffmpeg_encoder_mode: FFmpegEncoderMode = FFmpegEncoderMode.AUTO

    @classmethod
    def from_env(cls) -> "AccelerationConfig":
        """Load acceleration configuration from environment variables."""
        raw_device = os.environ.get("ACCELERATION_DEVICE", "auto").strip().lower()
        device_mode = DeviceMode.AUTO
        if raw_device == "cuda":
            device_mode = DeviceMode.CUDA
        elif raw_device == "cpu":
            device_mode = DeviceMode.CPU

        raw_whisper_dev = os.environ.get("WHISPER_DEVICE", raw_device).strip().lower()
        whisper_device = DeviceMode.AUTO
        if raw_whisper_dev == "cuda":
            whisper_device = DeviceMode.CUDA
        elif raw_whisper_dev == "cpu":
            whisper_device = DeviceMode.CPU

        whisper_compute_type = os.environ.get("WHISPER_COMPUTE_TYPE", "auto").strip().lower()

        raw_ffmpeg = os.environ.get("FFMPEG_ACCELERATION", "auto").strip().lower()
        ffmpeg_mode = FFmpegEncoderMode.AUTO
        if raw_ffmpeg in ("nvenc", "cuda", "gpu"):
            ffmpeg_mode = FFmpegEncoderMode.NVENC
        elif raw_ffmpeg in ("cpu", "libx264", "none"):
            ffmpeg_mode = FFmpegEncoderMode.CPU

        return cls(
            device_mode=device_mode,
            whisper_device=whisper_device,
            whisper_compute_type=whisper_compute_type,
            ffmpeg_encoder_mode=ffmpeg_mode,
        )


@dataclass(frozen=True)
class AccelerationReport:
    """Detailed hardware acceleration diagnostics and active capabilities."""

    cuda_available: bool
    cuda_device_count: int
    cuda_device_names: List[str]
    nvenc_available: bool
    configured_device_mode: str
    effective_whisper_device: str
    effective_whisper_compute_type: str
    effective_video_encoder: str


class HardwareAccelerationService:
    """Service responsible for hardware acceleration discovery, configuration, and execution."""

    def __init__(self, config: Optional[AccelerationConfig] = None) -> None:
        self.config = config or AccelerationConfig.from_env()
        self._cuda_available_cache: Optional[bool] = None
        self._cuda_device_count_cache: Optional[int] = None
        self._cuda_device_names_cache: Optional[List[str]] = None
        self._nvenc_available_cache: Optional[bool] = None

    def is_cuda_available(self) -> bool:
        """Check whether NVIDIA CUDA runtime is operational on this host."""
        if self._cuda_available_cache is not None:
            return self._cuda_available_cache

        # Check ctranslate2 CUDA device count (used by faster-whisper)
        try:
            import ctranslate2

            device_count = ctranslate2.get_cuda_device_count()
            if device_count > 0:
                self._cuda_available_cache = True
                self._cuda_device_count_cache = device_count
                return True
        except Exception:
            pass

        # Fallback probe via PyTorch if installed
        try:
            import torch

            if torch.cuda.is_available() and torch.cuda.device_count() > 0:
                self._cuda_available_cache = True
                self._cuda_device_count_cache = torch.cuda.device_count()
                return True
        except Exception:
            pass

        # Fallback probe via nvidia-smi command
        if shutil.which("nvidia-smi"):
            try:
                res = subprocess.run(
                    ["nvidia-smi", "-L"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
                if res.returncode == 0 and "GPU" in res.stdout:
                    gpu_lines = [l for l in res.stdout.strip().splitlines() if "GPU" in l]
                    self._cuda_available_cache = True
                    self._cuda_device_count_cache = max(1, len(gpu_lines))
                    self._cuda_device_names_cache = gpu_lines
                    return True
            except Exception:
                pass

        self._cuda_available_cache = False
        self._cuda_device_count_cache = 0
        self._cuda_device_names_cache = []
        return False

    def get_cuda_device_count(self) -> int:
        """Return the number of detected NVIDIA CUDA devices."""
        if self._cuda_device_count_cache is None:
            self.is_cuda_available()
        return self._cuda_device_count_cache or 0

    def get_cuda_device_names(self) -> List[str]:
        """Return human-readable names of detected NVIDIA CUDA devices."""
        if self._cuda_device_names_cache is not None:
            return list(self._cuda_device_names_cache)

        names: List[str] = []
        try:
            import torch

            if torch.cuda.is_available():
                for idx in range(torch.cuda.device_count()):
                    names.append(torch.cuda.get_device_name(idx))
                self._cuda_device_names_cache = names
                return names
        except Exception:
            pass

        if shutil.which("nvidia-smi"):
            try:
                res = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
                if res.returncode == 0 and res.stdout.strip():
                    names = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
                    self._cuda_device_names_cache = names
                    return names
            except Exception:
                pass

        if self.is_cuda_available():
            names = [f"NVIDIA CUDA Device #{i}" for i in range(self.get_cuda_device_count())]

        self._cuda_device_names_cache = names
        return names

    def is_nvenc_available(self, ffmpeg_executable: str = "ffmpeg") -> bool:
        """Check if FFmpeg has h264_nvenc encoder support compiled and usable."""
        if self._nvenc_available_cache is not None:
            return self._nvenc_available_cache

        executable = shutil.which(ffmpeg_executable) or ffmpeg_executable
        try:
            res = subprocess.run(
                [executable, "-encoders"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if res.returncode == 0 and "h264_nvenc" in res.stdout:
                # If CUDA is also available, NVENC is highly likely operational
                self._nvenc_available_cache = True
                return True
        except Exception:
            pass

        self._nvenc_available_cache = False
        return False

    def resolve_whisper_device_and_compute_type(
        self,
        device_override: Optional[str] = None,
        compute_override: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Resolve the effective Whisper device and compute_type based on hardware and config.

        Returns:
            Tuple[str, str]: (device, compute_type) e.g. ("cuda", "float16") or ("cpu", "int8").
        """
        req_dev = (device_override or self.config.whisper_device.value).lower()
        req_compute = (compute_override or self.config.whisper_compute_type).lower()

        if req_dev == "cpu":
            effective_dev = "cpu"
            effective_compute = "int8" if req_compute == "auto" else req_compute
            return effective_dev, effective_compute

        if req_dev == "cuda":
            if self.is_cuda_available():
                effective_dev = "cuda"
                effective_compute = "float16" if req_compute == "auto" else req_compute
            else:
                logger.warning("CUDA requested for Whisper but no CUDA devices found. Falling back to CPU.")
                effective_dev = "cpu"
                effective_compute = "int8" if req_compute == "auto" else req_compute
            return effective_dev, effective_compute

        # Auto mode
        if self.is_cuda_available():
            effective_dev = "cuda"
            effective_compute = "float16" if req_compute == "auto" else req_compute
        else:
            effective_dev = "cpu"
            effective_compute = "int8" if req_compute == "auto" else req_compute

        return effective_dev, effective_compute

    def should_use_nvenc(self, ffmpeg_executable: str = "ffmpeg") -> bool:
        """Determine if FFmpeg should attempt NVENC GPU encoding."""
        if self.config.ffmpeg_encoder_mode == FFmpegEncoderMode.CPU:
            return False
        if self.config.ffmpeg_encoder_mode == FFmpegEncoderMode.NVENC:
            return self.is_nvenc_available(ffmpeg_executable)
        # Auto mode: use NVENC if both CUDA and h264_nvenc encoder are available
        return self.is_cuda_available() and self.is_nvenc_available(ffmpeg_executable)

    def get_video_encoder_flags(
        self,
        use_nvenc: bool,
        pixel_format: str = "yuv420p",
    ) -> List[str]:
        """Generate standard FFmpeg video encoder CLI flags for NVENC (GPU) or libx264 (CPU)."""
        if use_nvenc:
            return [
                "-c:v",
                "h264_nvenc",
                "-preset",
                "p4",
                "-pix_fmt",
                pixel_format,
            ]
        return [
            "-c:v",
            "libx264",
            "-pix_fmt",
            pixel_format,
        ]

    def run_ffmpeg_with_fallback(
        self,
        command_builder: Callable[[bool], List[str]],
        output_file_validator: Optional[Callable[[], bool]] = None,
        ffmpeg_executable: str = "ffmpeg",
    ) -> subprocess.CompletedProcess:
        """Execute an FFmpeg command with GPU NVENC if available, falling back to CPU on failure.

        Args:
            command_builder: Function taking `use_nvenc: bool` and returning full command list.
            output_file_validator: Optional predicate returning True if output file was created.
            ffmpeg_executable: Path or name of FFmpeg executable.

        Returns:
            subprocess.CompletedProcess: Successful FFmpeg process result.

        Raises:
            subprocess.CalledProcessError or Exception: If both NVENC and CPU attempts fail.
        """
        try_nvenc = self.should_use_nvenc(ffmpeg_executable)

        if try_nvenc:
            gpu_cmd = command_builder(True)
            try:
                result = subprocess.run(
                    gpu_cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                success = result.returncode == 0
                if success and output_file_validator:
                    success = output_file_validator()

                if success:
                    return result

                logger.warning(
                    f"FFmpeg NVENC encoding failed (returncode={result.returncode}, stderr={result.stderr[:200]}). "
                    "Falling back transparently to CPU libx264 encoding."
                )
            except Exception as exc:
                logger.warning(
                    f"FFmpeg NVENC execution threw exception: {exc}. Falling back to CPU libx264 encoding."
                )

        # CPU Execution (libx264)
        cpu_cmd = command_builder(False)
        return subprocess.run(
            cpu_cmd,
            capture_output=True,
            text=True,
            check=False,
        )

    def get_acceleration_report(self, ffmpeg_executable: str = "ffmpeg") -> AccelerationReport:
        """Generate a complete diagnostic report of acceleration status and active modes."""
        cuda_avail = self.is_cuda_available()
        nvenc_avail = self.is_nvenc_available(ffmpeg_executable)
        w_dev, w_comp = self.resolve_whisper_device_and_compute_type()
        use_nvenc = self.should_use_nvenc(ffmpeg_executable)

        return AccelerationReport(
            cuda_available=cuda_avail,
            cuda_device_count=self.get_cuda_device_count(),
            cuda_device_names=self.get_cuda_device_names(),
            nvenc_available=nvenc_avail,
            configured_device_mode=self.config.device_mode.value,
            effective_whisper_device=w_dev,
            effective_whisper_compute_type=w_comp,
            effective_video_encoder="h264_nvenc" if use_nvenc else "libx264",
        )


# Global default instance
default_acceleration_service = HardwareAccelerationService()
