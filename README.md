# AI Shorts Generator

## Purpose

AI Shorts Generator is a full-stack application designed to help creators
automatically turn long-form video content into short, engaging clips
("shorts") suitable for platforms such as YouTube Shorts, Instagram Reels,
and TikTok. The project aims to combine video processing, AI-driven content
analysis, and an intuitive web interface so users can generate short-form
video content with minimal manual editing.

> **Note:** This is an early-stage project. The features described below
> represent the planned architecture and direction of the project, not
> functionality that currently exists in this repository.

## Planned Architecture

The project is organized as a full-stack application with a clear
separation between backend and frontend concerns:

```
ai-shorts-generator/
├── backend/            # Python backend application
│   └── app/            # FastAPI application package (routes, services, models)
├── frontend/           # React + TypeScript frontend application
├── tests/              # Backend and frontend test suites
├── .gitignore
└── README.md
```

- **Backend**: Planned to be built with [FastAPI](https://fastapi.tiangolo.com/)
  (Python), responsible for handling API requests, orchestrating video and
  AI processing pipelines, managing uploads/outputs, and exposing endpoints
  for the frontend to consume.
- **Frontend**: Planned to be built with [React](https://react.dev/) and
  [TypeScript](https://www.typescriptlang.org/), providing the user
  interface for uploading videos, configuring short generation options, and
  reviewing/downloading generated shorts.
- **Tests**: A dedicated directory for backend and frontend automated tests
  to ensure reliability as functionality is added.

Future planned capabilities (not yet implemented) include:

- Video ingestion and processing (e.g., trimming, resizing, captioning)
- AI-based content analysis (e.g., highlight/key-moment detection)
- Transcription of source video/audio
- Downloading source content from platforms such as YouTube
- User authentication and account management
- Payments/subscription handling
- Deployment tooling and infrastructure configuration

## Current Development Stage

The backend API and core ingestion/inspection services are under active development:

- `backend/app/main.py` — FastAPI application providing job creation and job status endpoints.
- `backend/app/models.py` — Pydantic models for `VideoSource`, `JobStatus`, `VideoJobRequest`, `VideoJobResponse`, `IngestedVideo`, and `VideoMetadata`.
- `backend/app/services/job_service.py` — Job management and in-memory job store.
- `backend/app/services/video_ingestion_service.py` — Video ingestion abstraction and single-video YouTube download integration via `yt-dlp`.
- `backend/app/services/video_metadata_service.py` — Media metadata extraction (duration, dimensions, format, file size) via `ffprobe`.
- `backend/app/services/media_tools_service.py` — Health-check service for external tool availability (`ffmpeg`, `ffprobe`, `yt-dlp`).
- `tests/` — Automated test suite with unit tests and mocked integration tests.

## Getting Started

### 1. Python Environment Setup

1. Create and activate a Python virtual environment:
   ```powershell
   python -m venv backend/venv
   .\backend\venv\Scripts\Activate.ps1
   ```
2. Install Python dependencies:
   ```powershell
   pip install -r backend/requirements.txt
   pip install -r backend/requirements-dev.txt
   ```

### 2. External Media Dependencies (FFmpeg and ffprobe)

Video metadata inspection and subsequent video processing (cutting, filtering, transcoding) require **FFmpeg** and **ffprobe** system binaries to be installed and available on your system `PATH`.

> **Important:** FFmpeg binaries are external system tools and must **not** be bundled into or committed to this repository.

#### Windows Installation Options

Choose one of the following trusted installation methods:

* **Option A: Via WinGet (Recommended)**
  Open PowerShell as Administrator or regular user and run:
  ```powershell
  winget install Gyan.FFmpeg
  ```
  *(or `winget install "FFmpeg (Essentials Build)"`)*

* **Option B: Via Chocolatey**
  ```powershell
  choco install ffmpeg
  ```

* **Option C: Via Scoop**
  ```powershell
  scoop install ffmpeg
  ```

* **Option D: Manual Download from Official Builds**
  1. Download a release build (e.g. from [gyan.dev FFmpeg Builds](https://www.gyan.dev/ffmpeg/builds/) or [BtbN FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds/releases), trusted resources linked on [ffmpeg.org](https://ffmpeg.org/download.html)).
  2. Extract the archive to a local folder (e.g. `C:\ffmpeg`).
  3. Add the `bin` directory containing `ffmpeg.exe` and `ffprobe.exe` to your Windows User or System `PATH` environment variable.
  4. Restart your terminal session for the `PATH` change to take effect.

#### Verifying Installation

Verify that both tools are discoverable in a new terminal session:

```powershell
ffmpeg -version
ffprobe -version
```

Both commands should display version information without command-not-found errors.

### 3. GPU Acceleration & NVIDIA CUDA Support

AI Shorts Generator includes full GPU acceleration for NVIDIA hardware with transparent automatic CPU fallback:
- **GPU-Accelerated Whisper STT**: Faster speech-to-text transcription powered by CTranslate2 CUDA runtime (`float16` precision).
- **FFmpeg NVENC Encoding**: Fast H.264 hardware encoding (`h264_nvenc`) for clipping, 9:16 vertical formatting, and subtitle burning.
- **Transparent CPU Fallback**: Automatically falls back to CPU execution (`int8` Whisper, `libx264` FFmpeg) if CUDA or NVENC are unavailable, out of memory, or encounter driver errors.

#### Configuration (.env)
```ini
ACCELERATION_DEVICE=auto       # "auto", "cuda", or "cpu"
WHISPER_DEVICE=auto            # "auto", "cuda", or "cpu"
WHISPER_COMPUTE_TYPE=auto      # "auto", "float16", "int8_float16", "int8"
FFMPEG_ACCELERATION=auto       # "auto", "nvenc", or "cpu"
```

#### Running with Docker GPU Acceleration
To run the full stack with NVIDIA GPU passthrough enabled:
```powershell
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

### 4. Cloud Storage: AWS S3 & Cloudflare R2 Integration

AI Shorts Generator provides native cloud object storage for source video uploads and generated shorts artifacts:
- **Supported Backends**: `local` (default), `s3` (AWS S3), `r2` (Cloudflare R2), `minio`, and `wasabi`.
- **Pure Python SigV4 Pre-Signing**: Secure presigned media URLs with custom expiry and zero heavy external dependencies.
- **Exponential Backoff Retries**: Automatic retries on transient network and 5xx/429 storage errors.
- **Automatic Local Fallback**: Seamless fallback to local disk storage if cloud credentials or network connections are unavailable.
- **Diagnostics API**: Live storage status and health reporting via `GET /api/system/storage`.

#### S3 / Cloudflare R2 Configuration (.env)
```ini
STORAGE_BACKEND=s3                      # "local", "s3", "r2", "minio", "wasabi"
S3_ENDPOINT=https://<account_id>.r2.cloudflarestorage.com  # Required for R2/MinIO, optional for AWS
S3_REGION=us-east-1                     # "us-east-1" for AWS, "auto" for Cloudflare R2
S3_BUCKET=ai-shorts-bucket
S3_ACCESS_KEY_ID=your_access_key
S3_SECRET_ACCESS_KEY=your_secret_key
S3_PUBLIC_BASE_URL=https://media.domain.com  # Optional custom CDN domain
S3_PRESIGNED_EXPIRY=3600               # Presigned URL expiry in seconds
STORAGE_MAX_RETRIES=3                   # Retry attempts on transient network errors
STORAGE_ENABLE_LOCAL_FALLBACK=true      # Seamless fallback to disk storage on failure
```

### 5. Running Tests

Run the complete test suite:

```powershell
.\backend\venv\Scripts\python.exe -m pytest tests -q
```

