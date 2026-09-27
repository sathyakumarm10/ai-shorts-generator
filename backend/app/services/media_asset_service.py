"""Minimal persistent ownership registry for uploaded source media."""

from datetime import datetime, timezone
import os
from pathlib import Path
import secrets
import sqlite3
from typing import Any, Optional, Protocol

from app.models import MediaAsset
from app.services.db import DatabaseBackend, DatabaseConfig
from app.services.db_migrations import run_postgres_migrations, run_sqlite_migrations


class MediaAssetError(Exception):
    """Raised when an asset cannot be stored or safely resolved."""


class MediaAssetStore(Protocol):
    def insert(self, asset: MediaAsset) -> None: ...
    def get(self, asset_id: str) -> Optional[MediaAsset]: ...


def _row_to_asset(row: Any) -> MediaAsset:
    created_at = row["created_at"]
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return MediaAsset(
        asset_id=row["asset_id"],
        owner_id=row["owner_id"],
        stored_path=row["stored_path"],
        original_filename=row["original_filename"],
        created_at=created_at,
        size_bytes=row["size_bytes"],
        status=row["status"],
    )


class SQLiteMediaAssetStore:
    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._is_memory = db_path == ":memory:"
        if not self._is_memory:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._shared_conn = self._new_connection() if self._is_memory else None
        conn = self._connect()
        run_sqlite_migrations(conn)
        if self._shared_conn is None:
            conn.close()

    def _new_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _connect(self) -> sqlite3.Connection:
        return self._shared_conn or self._new_connection()

    def insert(self, asset: MediaAsset) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO media_assets
                (asset_id, owner_id, stored_path, original_filename, created_at, size_bytes, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    asset.asset_id,
                    asset.owner_id,
                    asset.stored_path,
                    asset.original_filename,
                    asset.created_at.isoformat(),
                    asset.size_bytes,
                    asset.status,
                ),
            )
            conn.commit()
        finally:
            if self._shared_conn is None:
                conn.close()

    def get(self, asset_id: str) -> Optional[MediaAsset]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM media_assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
            return _row_to_asset(row) if row else None
        finally:
            if self._shared_conn is None:
                conn.close()


class PostgresMediaAssetStore:
    def __init__(self, database_url: str) -> None:
        import psycopg

        self.database_url = database_url
        with psycopg.connect(database_url) as conn:
            run_postgres_migrations(conn)

    def insert(self, asset: MediaAsset) -> None:
        import psycopg

        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO media_assets
                    (asset_id, owner_id, stored_path, original_filename, created_at, size_bytes, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (
                        asset.asset_id,
                        asset.owner_id,
                        asset.stored_path,
                        asset.original_filename,
                        asset.created_at,
                        asset.size_bytes,
                        asset.status,
                    ),
                )

    def get(self, asset_id: str) -> Optional[MediaAsset]:
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(self.database_url) as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute("SELECT * FROM media_assets WHERE asset_id = %s", (asset_id,))
                row = cursor.fetchone()
        return _row_to_asset(row) if row else None


class MediaAssetService:
    def __init__(
        self,
        store: Optional[MediaAssetStore] = None,
        upload_root: Optional[Path | str] = None,
    ) -> None:
        self.store = store or _create_asset_store()
        configured_root = upload_root or os.environ.get(
            "UPLOAD_DIR", str(Path("downloads") / "uploads")
        )
        self.upload_root = Path(configured_root).resolve()

    def create_asset(
        self,
        *,
        owner_id: str,
        stored_path: Path | str,
        original_filename: str,
        size_bytes: int,
    ) -> MediaAsset:
        resolved_path = self._validate_stored_path(stored_path)
        asset = MediaAsset(
            asset_id=secrets.token_urlsafe(32),
            owner_id=owner_id,
            stored_path=str(resolved_path),
            original_filename=original_filename,
            created_at=datetime.now(timezone.utc),
            size_bytes=size_bytes,
            status="uploaded",
        )
        self.store.insert(asset)
        return asset

    def get_asset(self, asset_id: str) -> Optional[MediaAsset]:
        return self.store.get(asset_id)

    def resolve_owned_asset(self, asset_id: str, owner_id: str) -> Path:
        asset = self.store.get(asset_id)
        if asset is None:
            raise MediaAssetError("Uploaded asset was not found.")
        if asset.owner_id != owner_id:
            raise PermissionError("Uploaded asset belongs to another owner.")
        if asset.status != "uploaded":
            raise MediaAssetError("Uploaded asset is not available for processing.")
        path = self._validate_stored_path(asset.stored_path)
        if not path.is_file():
            raise MediaAssetError("Uploaded asset file was not found.")
        return path

    def _validate_stored_path(self, stored_path: Path | str) -> Path:
        resolved = Path(stored_path).resolve()
        try:
            resolved.relative_to(self.upload_root)
        except ValueError as exc:
            raise MediaAssetError("Asset path escapes the upload root.") from exc
        return resolved


def _create_asset_store() -> MediaAssetStore:
    config = DatabaseConfig.from_env()
    if config.backend == DatabaseBackend.POSTGRESQL and config.database_url:
        try:
            return PostgresMediaAssetStore(config.database_url)
        except Exception:
            if not config.enable_local_fallback:
                raise
    return SQLiteMediaAssetStore(config.sqlite_job_db_path)


default_media_asset_service = MediaAssetService()
