# ==============================================================================
# AI Shorts Generator - Production Backend Dockerfile
# Multi-stage/Slim Debian image with FFmpeg, Whisper/CTranslate2 dependencies, and fonts
# ==============================================================================

FROM python:3.12-slim-bookworm

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    HOST=0.0.0.0 \
    HF_HOME=/app/model_cache

WORKDIR /app

# Install system runtime dependencies:
# - ffmpeg: audio/video trimming, filtering, vertical conversion, subtitle burning
# - libgomp1: OpenMP shared library for CTranslate2 / faster-whisper
# - fontconfig & fonts-dejavu-core: font rendering for ASS/SRT caption overlays
# - ca-certificates: TLS/HTTPS verification for YouTube & AI providers
# - curl: container healthcheck probing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgomp1 \
    fontconfig \
    fonts-dejavu-core \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python application dependencies
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt

# Create application data, output, upload, and model cache directories
RUN mkdir -p /app/data /app/outputs /app/downloads/uploads /app/model_cache

# Copy application source code
COPY backend/app /app/app

# Expose FastAPI HTTP port
EXPOSE 8000

# Container healthcheck against /health endpoint
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start FastAPI application via Uvicorn ASGI server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
