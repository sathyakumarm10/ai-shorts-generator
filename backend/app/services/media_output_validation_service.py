"""Reusable ffprobe validation for generated video artifacts."""

from pathlib import Path
from typing import Optional

from app.models import VideoMetadata
from app.services.video_metadata_service import VideoMetadataError, VideoMetadataService


class MediaOutputValidationError(Exception):
    """Raised when a generated video is missing, corrupt, or materially unexpected."""


class MediaOutputValidationService:
    def __init__(self, metadata_service: Optional[VideoMetadataService] = None) -> None:
        self.metadata_service = metadata_service or VideoMetadataService()

    def validate_video(
        self,
        path: Path | str,
        *,
        expected_duration_seconds: Optional[float] = None,
        expected_width: Optional[int] = None,
        expected_height: Optional[int] = None,
    ) -> VideoMetadata:
        output_path = Path(path)
        if not output_path.is_file():
            raise MediaOutputValidationError("Generated video file is missing.")
        try:
            if output_path.stat().st_size <= 0:
                raise MediaOutputValidationError("Generated video file is empty.")
        except OSError as exc:
            raise MediaOutputValidationError("Generated video file could not be inspected.") from exc

        try:
            metadata = self.metadata_service.extract_metadata(output_path)
        except VideoMetadataError as exc:
            raise MediaOutputValidationError("Generated video failed media validation.") from exc

        if expected_duration_seconds is not None:
            tolerance = max(2.0, expected_duration_seconds * 0.15)
            if abs(metadata.duration_seconds - expected_duration_seconds) > tolerance:
                raise MediaOutputValidationError("Generated video duration is outside the expected range.")

        if expected_width is not None and metadata.width != expected_width:
            raise MediaOutputValidationError("Generated video width does not match the requested output.")
        if expected_height is not None and metadata.height != expected_height:
            raise MediaOutputValidationError("Generated video height does not match the requested output.")

        return metadata
