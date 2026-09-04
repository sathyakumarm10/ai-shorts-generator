"""SQLite-backed persistent storage for job records.

Provides a lightweight thread-safe store that persists JobRecord instances
to a local SQLite database, enabling jobs to survive backend restarts.

The module handles serialization, schema management, and raw CRUD.
"""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import List, Optional

from app.models import (
    JobRecord,
    JobStatus,
    ShortsGenerationResult,
    VideoSource,
)
from app.services.db_migrations import run_sqlite_migrations

_INSERT_SQL = """\
INSERT INTO jobs (
    job_id, status, progress_percent, message,
    created_at, started_at, completed_at,
    error, result_json, source_json,
    clip_duration, number_of_clips, user_id,
    retry_count, queue_name
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

_UPDATE_SQL = """\
UPDATE jobs SET
    status           = ?,
    progress_percent = ?,
    message          = ?,
    started_at       = ?,
    completed_at     = ?,
    error            = ?,
    result_json      = ?,
    user_id          = ?,
    retry_count      = ?,
    queue_name       = ?
WHERE job_id = ?;
"""

_UPSERT_SQL = """\
INSERT OR REPLACE INTO jobs (
    job_id, status, progress_percent, message,
    created_at, started_at, completed_at,
    error, result_json, source_json,
    clip_duration, number_of_clips, user_id,
    retry_count, queue_name
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

_SELECT_SQL = "SELECT * FROM jobs WHERE job_id = ?;"
_SELECT_BY_USER_SQL = "SELECT * FROM jobs WHERE user_id = ? ORDER BY created_at DESC;"
_SELECT_ALL_SQL = "SELECT * FROM jobs ORDER BY created_at DESC;"
_DELETE_SQL = "DELETE FROM jobs WHERE job_id = ?;"


def _dt_to_str(dt: Optional[datetime]) -> Optional[str]:
    """Convert a datetime to ISO-8601 string (or None)."""
    return dt.isoformat() if dt is not None else None


def _str_to_dt(s: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 string back to a timezone-aware datetime (or None)."""
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _job_to_row(job: JobRecord) -> tuple:
    """Flatten a JobRecord into a tuple matching the INSERT column order."""
    return (
        job.job_id,
        job.status.value,
        job.progress_percent,
        job.message,
        _dt_to_str(job.created_at),
        _dt_to_str(job.started_at),
        _dt_to_str(job.completed_at),
        job.error,
        job.result.model_dump_json() if job.result else None,
        job.source.model_dump_json() if job.source else None,
        job.clip_duration,
        job.number_of_clips,
        job.user_id,
        getattr(job, "retry_count", 0),
        getattr(job, "queue_name", None),
    )


def _row_to_job(row: sqlite3.Row) -> JobRecord:
    """Reconstruct a JobRecord from a database row."""
    result: Optional[ShortsGenerationResult] = None
    if row["result_json"]:
        result = ShortsGenerationResult.model_validate_json(row["result_json"])

    source: Optional[VideoSource] = None
    if row["source_json"]:
        source = VideoSource.model_validate_json(row["source_json"])

    user_id: Optional[str] = None
    try:
        user_id = row["user_id"]
    except (IndexError, KeyError):
        user_id = None

    return JobRecord(
        job_id=row["job_id"],
        status=JobStatus(row["status"]),
        progress_percent=row["progress_percent"],
        message=row["message"],
        created_at=_str_to_dt(row["created_at"]) or datetime.now(timezone.utc),
        started_at=_str_to_dt(row["started_at"]),
        completed_at=_str_to_dt(row["completed_at"]) or (_str_to_dt(row["started_at"]) or _str_to_dt(row["created_at"]) or datetime.now(timezone.utc) if row["status"] == JobStatus.COMPLETED.value else None),
        error=row["error"],
        result=result,
        source=source,
        clip_duration=row["clip_duration"],
        number_of_clips=row["number_of_clips"],
        user_id=user_id,
    )


class SQLiteJobStore:
    """Thin persistence layer for JobRecords backed by a local SQLite file."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._is_memory = db_path == ":memory:"
        if not self._is_memory:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        if self._is_memory:
            self._shared_conn = self._new_connection()
        else:
            self._shared_conn = None

        self._init_schema()

    def _new_connection(self) -> sqlite3.Connection:
        """Create a brand-new SQLite connection."""
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        if not self._is_memory:
            conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _connect(self) -> sqlite3.Connection:
        """Return the shared connection (memory) or open a fresh one (file)."""
        if self._shared_conn is not None:
            return self._shared_conn
        return self._new_connection()

    def _init_schema(self) -> None:
        conn = self._connect()
        run_sqlite_migrations(conn)

    def insert(self, job: JobRecord) -> None:
        """Insert a brand-new JobRecord. Raises on duplicate job_id."""
        row = _job_to_row(job)
        with self._connect() as conn:
            conn.execute(_INSERT_SQL, row)

    def get(self, job_id: str) -> Optional[JobRecord]:
        """Fetch a single job by ID, or return None."""
        with self._connect() as conn:
            cursor = conn.execute(_SELECT_SQL, (job_id,))
            row = cursor.fetchone()
        if row is None:
            return None
        return _row_to_job(row)

    def list_by_user(self, user_id: Optional[str] = None) -> List[JobRecord]:
        """Fetch jobs owned by a specific user (or all jobs if user_id is None)."""
        with self._connect() as conn:
            if user_id:
                cursor = conn.execute(_SELECT_BY_USER_SQL, (user_id,))
            else:
                cursor = conn.execute(_SELECT_ALL_SQL)
            rows = cursor.fetchall()
        return [_row_to_job(r) for r in rows]

    def delete(self, job_id: str) -> bool:
        """Delete a job record by ID."""
        with self._connect() as conn:
            cursor = conn.execute(_DELETE_SQL, (job_id,))
            conn.commit()
            return cursor.rowcount > 0

    def update(self, job: JobRecord) -> None:
        """Update mutable columns of an existing job (status, progress, etc.)."""
        params = (
            job.status.value,
            job.progress_percent,
            job.message,
            _dt_to_str(job.started_at),
            _dt_to_str(job.completed_at),
            job.error,
            job.result.model_dump_json() if job.result else None,
            job.user_id,
            getattr(job, "retry_count", 0),
            getattr(job, "queue_name", None),
            job.job_id,
        )
        with self._connect() as conn:
            conn.execute(_UPDATE_SQL, params)

    def upsert(self, job: JobRecord) -> None:
        """Insert or fully replace a JobRecord (used by legacy proxies)."""
        row = _job_to_row(job)
        with self._connect() as conn:
            conn.execute(_UPSERT_SQL, row)
