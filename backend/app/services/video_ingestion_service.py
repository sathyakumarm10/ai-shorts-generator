"""Video ingestion service abstraction.

This module defines the service interface and domain exceptions for converting
a `VideoSource` (YouTube link, uploaded file reference, etc.) into a locally
accessible `IngestedVideo` reference for subsequent processing.

Actual downloading, network calls, file uploading, and processing are not
implemented yet and will be added in future stages.
"""

from app.models import IngestedVideo, VideoSource, VideoSourceType


class VideoIngestionError(Exception):
    """Domain exception raised when video ingestion fails or is unsupported."""

    pass


class VideoIngestionService:
    """Service abstraction responsible for ingesting video sources into local files.

    Given a `VideoSource`, implementations or methods ingest the content
    and produce an `IngestedVideo` model containing the local file path.
    """

    def ingest(self, source: VideoSource) -> IngestedVideo:
        """Ingest a video source and produce an IngestedVideo reference.

        Args:
            source: The VideoSource describing type and location.

        Returns:
            IngestedVideo: Contains the local file path to the ingested video.

        Raises:
            VideoIngestionError: If the source type cannot be ingested.
            NotImplementedError: For source types where ingestion logic is not yet built.
        """
        if source.type == VideoSourceType.YOUTUBE:
            # YouTube downloading requires external download capabilities (e.g. yt-dlp/pytube),
            # which are intentionally not implemented yet.
            raise NotImplementedError(
                "YouTube video ingestion is not implemented yet."
            )
        elif source.type == VideoSourceType.UPLOAD:
            # Upload handling / local validation is not yet implemented.
            raise NotImplementedError(
                "Upload video ingestion is not implemented yet."
            )
        else:
            raise VideoIngestionError(f"Unsupported video source type: {source.type}")
