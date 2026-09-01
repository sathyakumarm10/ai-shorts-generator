"""Video ingestion service.

This module provides the `VideoIngestionService` responsible for acquiring
source videos (e.g. from YouTube or local uploads) and making them available
locally as `IngestedVideo` objects containing validated local file paths.
"""

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

# pyrefly: ignore [missing-import-source]
import yt_dlp  # type: ignore

from app.models import IngestedVideo, VideoSource, VideoSourceType

# Default storage directory for downloaded source videos.
# Defaults to `downloads/sources` at project root level (ignored by git).
DEFAULT_DOWNLOAD_DIR = Path("downloads") / "sources"


class VideoIngestionError(Exception):
    """Domain exception raised when video ingestion fails or is unsupported."""

    pass


class VideoIngestionService:
    """Service responsible for ingesting video sources into local files.

    Given a `VideoSource`, this service ingests the video content and produces
    an `IngestedVideo` model containing the local file path.
    """

    def __init__(self, download_dir: Path | str = DEFAULT_DOWNLOAD_DIR) -> None:
        self.download_dir = Path(download_dir)

    def _ingest_youtube(self, location: str) -> IngestedVideo:
        """Download a single YouTube video using yt-dlp.

        Only legitimate, user-authorized single-video processing is supported.
        No cookies, credentials, playlists, or channels are processed.
        """
        self.download_dir.mkdir(parents=True, exist_ok=True)
        # Generate a safe, unique filename base to avoid collision or path traversal
        unique_id = uuid4().hex
        output_template = str(self.download_dir / f"yt_{unique_id}.%(ext)s")

        ydl_opts = {
            "outtmpl": output_template,
            # Select best single file with video+audio, or best video+best audio fallback
            "format": "best[ext=mp4]/bestvideo+bestaudio/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "no_color": True,
        }

        try:
            with yt_dlp.YoutubeDL(cast(Any, ydl_opts)) as ydl:
                info = ydl.extract_info(location, download=True)
                if not info:
                    raise VideoIngestionError("No video information could be retrieved from YouTube.")
                filename = ydl.prepare_filename(info)
                if not filename:
                    raise VideoIngestionError("Failed to determine downloaded video filename.")
                downloaded_file = Path(filename)
        except Exception as exc:
            raise VideoIngestionError(f"Failed to download YouTube video: {exc}") from exc

        if not downloaded_file.is_file():
            raise VideoIngestionError(
                f"Ingestion reported success, but expected video file was not found: {downloaded_file}"
            )

        return IngestedVideo(file_path=str(downloaded_file))

    def ingest(self, source: VideoSource) -> IngestedVideo:
        """Ingest a video source and produce an IngestedVideo reference.

        Args:
            source: The VideoSource describing type and location.

        Returns:
            IngestedVideo: Contains the local file path to the ingested video.

        Raises:
            VideoIngestionError: If download fails or the source type is unsupported.
            NotImplementedError: If ingestion for the source type is not implemented yet.
        """
        if source.type == VideoSourceType.YOUTUBE:
            return self._ingest_youtube(source.location)
        elif source.type == VideoSourceType.UPLOAD:
            # Check if source.location refers to an existing local file
            local_path = Path(source.location)
            if local_path.is_file():
                return IngestedVideo(file_path=str(local_path.resolve()))
            # Fallback for placeholder non-existent upload paths
            raise NotImplementedError(
                "Upload video ingestion is not implemented yet."
            )
        else:
            raise VideoIngestionError(f"Unsupported video source type: {source.type}")
