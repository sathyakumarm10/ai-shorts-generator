"""Job-scoped media storage service.

Provides a configurable media root under which every job gets its own
isolated subdirectory:

    {media_root}/
      jobs/
        {job_id}/
          source/      ← ingested / uploaded source video copy
          clips/       ← raw highlight clips
          vertical/    ← 9:16 vertical clips
          captioned/   ← caption-burned final clips

Key operations
--------------
* ``get_job_dir(job_id)``     – Return (and create) the per-job root dir.
* ``get_job_subdir(job_id, subdir)`` – Return (and create) a named subdir.
* ``copy_to_job_dir(src, job_id, subdir)`` – Copy a file into a job subdir.
* ``resolve_media_path(rel_or_abs)`` – Safely resolve a client-supplied path.
* ``to_relative_path(abs_path)`` – Convert absolute → relative to media_root.
* ``to_media_url(abs_path)``   – Build ``/api/media?path=<relative>`` URL.

Security
--------
All ``resolve_media_path`` calls verify the resolved path stays within the
configured media root, rejecting ``..`` traversal, symlink escapes, and
paths rooted outside the tree.
"""

import logging
import shutil
from pathlib import Path
from typing import Dict, Optional
from uuid import uuid4

from app.services.storage_service import S3StorageService, StorageService, default_storage_service

logger = logging.getLogger(__name__)

# Default media root (relative to CWD at runtime; overridable via constructor).
DEFAULT_MEDIA_ROOT = Path("outputs")


class MediaStorageError(Exception):
    """Raised when a media storage or path-traversal violation occurs."""


class MediaStorageService:
    """Service managing job-scoped directory layout inside a media root.

    Parameters
    ----------
    media_root : Path | str
        Absolute or relative path to the root directory that holds all
        job artefacts.  Defaults to ``outputs/``.
    storage_service : StorageService | None
        Underlying object storage backend (local, S3, Cloudflare R2).
    """

    # Sub-directory names within each job directory
    SOURCE_SUBDIR = "source"
    CLIPS_SUBDIR = "clips"
    VERTICAL_SUBDIR = "vertical"
    CAPTIONED_SUBDIR = "captioned"

    def __init__(
        self,
        media_root: Path | str = DEFAULT_MEDIA_ROOT,
        storage_service: Optional[StorageService] = None,
    ) -> None:
        self.media_root = Path(media_root).resolve()
        self.storage_service = storage_service or default_storage_service

    # ------------------------------------------------------------------ #
    # Directory helpers                                                    #
    # ------------------------------------------------------------------ #

    def get_job_dir(self, job_id: str) -> Path:
        """Return the per-job root directory, creating it if absent."""
        self._validate_job_id(job_id)
        job_dir = self.media_root / "jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        return job_dir

    def get_job_subdir(self, job_id: str, subdir: str) -> Path:
        """Return a named subdirectory inside the job directory, creating it."""
        self._validate_job_id(job_id)
        self._validate_subdir_name(subdir)
        path = self.get_job_dir(job_id) / subdir
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ------------------------------------------------------------------ #
    # File operations                                                      #
    # ------------------------------------------------------------------ #

    def copy_to_job_dir(
        self,
        source_path: Path | str,
        job_id: str,
        subdir: str,
        filename: Optional[str] = None,
    ) -> Path:
        """Copy *source_path* into ``{media_root}/jobs/{job_id}/{subdir}/``.

        Parameters
        ----------
        source_path : Path | str
            Existing file to copy.
        job_id : str
            Target job identifier.
        subdir : str
            Target subdirectory name (e.g. "source", "clips").
        filename : str | None
            Destination filename.  If *None*, the source filename is kept.

        Returns
        -------
        Path
            Absolute path to the newly copied file inside the job directory.
        """
        src = Path(source_path)
        if not src.is_file():
            raise MediaStorageError(f"Source file not found: {src}")

        dest_dir = self.get_job_subdir(job_id, subdir)
        dest_name = filename or src.name
        dest_path = dest_dir / dest_name

        # Avoid clobbering existing files with colliding names
        if dest_path.exists():
            stem = src.stem
            suffix = src.suffix
            dest_path = dest_dir / f"{stem}_{uuid4().hex[:8]}{suffix}"

        shutil.copy2(str(src), str(dest_path))
        return dest_path

    # ------------------------------------------------------------------ #
    # Path resolution & security                                          #
    # ------------------------------------------------------------------ #

    def resolve_media_path(self, path: str | Path) -> Path:
        """Safely resolve *path* to an absolute path inside ``media_root``.

        Accepts either:
        * A **relative** path (treated as relative to ``media_root``).
        * An **absolute** path that must already be inside ``media_root``.

        Raises
        ------
        MediaStorageError
            If the resolved path escapes ``media_root`` or does not exist.
        """
        p = Path(path)

        if p.is_absolute():
            resolved = p.resolve()
        else:
            resolved = (self.media_root / p).resolve()

        # Strict containment check — the resolved path must be a descendant
        # of media_root (or equal to it, though serving the root itself is
        # blocked by the "is_file" check at the call site).
        try:
            resolved.relative_to(self.media_root)
        except ValueError:
            raise MediaStorageError(
                f"Path '{path}' escapes the media root and cannot be served."
            )

        return resolved

    def to_relative_path(self, abs_path: Path | str) -> str:
        """Convert an absolute path to a forward-slash path relative to ``media_root``.

        Returns the relative path string (e.g. ``jobs/abc/clips/clip_xyz.mp4``).

        Raises
        ------
        MediaStorageError
            If the path is not inside ``media_root``.
        """
        p = Path(abs_path).resolve()
        try:
            rel = p.relative_to(self.media_root)
        except ValueError:
            raise MediaStorageError(
                f"Path '{abs_path}' is not inside media root '{self.media_root}'."
            )
        # Use forward slashes for URL portability
        return rel.as_posix()

    def to_media_url(self, abs_path: Path | str) -> str:
        """Build a browser-accessible ``/api/media?path=<relative>`` or signed cloud URL.

        Parameters
        ----------
        abs_path : Path | str
            Absolute path to a media file inside ``media_root``.

        Returns
        -------
        str
            Relative URL string or presigned cloud URL.
        """
        rel = self.to_relative_path(abs_path)
        if isinstance(self.storage_service, S3StorageService) and self.storage_service.access_key_id:
            try:
                return self.storage_service.get_presigned_url(rel)
            except Exception:
                pass
        return f"/api/media?path={rel}"

    def sync_job_to_cloud(self, job_id: str) -> Dict[str, str]:
        """Upload all generated media artifacts for job_id to cloud storage.

        Returns
        -------
        Dict[str, str]
            Map of relative paths to cloud storage URLs.
        """
        self._validate_job_id(job_id)
        job_dir = self.media_root / "jobs" / job_id
        uploaded: Dict[str, str] = {}

        if not job_dir.is_dir():
            return uploaded

        for file_path in job_dir.rglob("*"):
            if file_path.is_file():
                try:
                    rel_key = file_path.relative_to(self.media_root).as_posix()
                    url = self.storage_service.upload_file(local_source_path=file_path, destination_key=rel_key)
                    uploaded[rel_key] = url
                except Exception as exc:
                    logger.warning(f"Failed to sync '{file_path.name}' to cloud storage: {exc}")

        return uploaded

    def delete_job_media(self, job_id: str) -> None:
        """Delete local media directory and cloud storage prefix for job_id."""
        self._validate_job_id(job_id)
        job_dir = self.media_root / "jobs" / job_id

        # Clean up local directory
        if job_dir.is_dir():
            shutil.rmtree(str(job_dir), ignore_errors=True)

        # Clean up cloud storage prefix
        try:
            self.storage_service.delete_prefix(f"jobs/{job_id}/")
        except Exception as exc:
            logger.warning(f"Failed to clean up cloud storage for job '{job_id}': {exc}")

    # ------------------------------------------------------------------ #
    # Validation helpers                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate_job_id(job_id: str) -> None:
        if not job_id or not job_id.strip():
            raise MediaStorageError("job_id cannot be empty.")
        # Guard against path traversal via job_id itself
        if ".." in job_id or "/" in job_id or "\\" in job_id:
            raise MediaStorageError(
                f"job_id contains invalid characters: '{job_id}'"
            )

    @staticmethod
    def _validate_subdir_name(subdir: str) -> None:
        if not subdir or not subdir.strip():
            raise MediaStorageError("subdir name cannot be empty.")
        if ".." in subdir or "/" in subdir or "\\" in subdir:
            raise MediaStorageError(
                f"subdir name contains invalid characters: '{subdir}'"
            )


# ---------------------------------------------------------------------------
# Module-level default instance
# ---------------------------------------------------------------------------

default_media_storage = MediaStorageService()
