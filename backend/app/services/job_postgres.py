"""PostgreSQL persistence store for Job records.

Provides robust, thread-safe Job storage backed by PostgreSQL with connection
pooling, transactional safety, and automatic additive migrations.
"""

from datetime import datetime, timezone
import logging
from typing import Any, List, Optional

import psycopg
from psycopg.rows import dict_row

from app.models import (
    JobRecord,
    JobStatus,
    ShortsGenerationResult,
    VideoSource,
)
from app.services.db_migrations import run_postgres_migrations

logger = logging.getLogger(__name__)

_INSERT_SQL = """\
INSERT INTO jobs (
    job_id, status, progress_percent, message,
    created_at, started_at, completed_at,
    error, result_json, source_json,
    clip_duration, number_of_clips, user_id,
    retry_count, queue_name
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
"""

_UPDATE_SQL = """\
UPDATE jobs SET
    status           = %s,
    progress_percent = %s,
    message          = %s,
    started_at       = %s,
    completed_at     = %s,
    error            = %s,
    result_json      = %s,
    user_id          = %s,
    retry_count      = %s,
    queue_name       = %s
WHERE job_id = %s;
"""

_UPSERT_SQL = """\
INSERT INTO jobs (
    job_id, status, progress_percent, message,
    created_at, started_at, completed_at,
    error, result_json, source_json,
    clip_duration, number_of_clips, user_id,
    retry_count, queue_name
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (job_id) DO UPDATE SET
    status           = EXCLUDED.status,
    progress_percent = EXCLUDED.progress_percent,
    message          = EXCLUDED.message,
    started_at       = EXCLUDED.started_at,
    completed_at     = EXCLUDED.completed_at,
    error            = EXCLUDED.error,
    result_json      = EXCLUDED.result_json,
    user_id          = EXCLUDED.user_id,
    retry_count      = EXCLUDED.retry_count,
    queue_name       = EXCLUDED.queue_name;
"""

_SELECT_SQL = "SELECT * FROM jobs WHERE job_id = %s;"
_SELECT_BY_USER_SQL = "SELECT * FROM jobs WHERE user_id = %s ORDER BY created_at DESC;"
_SELECT_ALL_SQL = "SELECT * FROM jobs ORDER BY created_at DESC;"
_DELETE_SQL = "DELETE FROM jobs WHERE job_id = %s;"


def _job_to_params(job: JobRecord) -> tuple:
    """Flatten JobRecord to PostgreSQL query parameters."""
    return (
        job.job_id,
        job.status.value,
        job.progress_percent,
        job.message,
        job.created_at,
        job.started_at,
        job.completed_at,
        job.error,
        job.result.model_dump_json() if job.result else None,
        job.source.model_dump_json() if job.source else None,
        job.clip_duration,
        job.number_of_clips,
        job.user_id,
        getattr(job, "retry_count", 0),
        getattr(job, "queue_name", None),
    )


def _row_to_job(row: Any) -> JobRecord:
    """Map PostgreSQL dict row to JobRecord."""
    result: Optional[ShortsGenerationResult] = None
    if row.get("result_json"):
        result = ShortsGenerationResult.model_validate_json(row["result_json"])

    source: Optional[VideoSource] = None
    if row.get("source_json"):
        source = VideoSource.model_validate_json(row["source_json"])

    created_at = row["created_at"]
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    started_at = row.get("started_at")
    if isinstance(started_at, str):
        started_at = datetime.fromisoformat(started_at)
    if started_at and started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)

    completed_at = row.get("completed_at")
    if isinstance(completed_at, str):
        completed_at = datetime.fromisoformat(completed_at)
    if completed_at and completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=timezone.utc)
    if (row.get("status") == JobStatus.COMPLETED.value or row.get("status") == JobStatus.COMPLETED) and completed_at is None:
        completed_at = started_at or created_at or datetime.now(timezone.utc)

    return JobRecord(
        job_id=row["job_id"],
        status=JobStatus(row["status"]),
        progress_percent=float(row["progress_percent"]),
        message=row["message"],
        created_at=created_at,
        started_at=started_at,
        completed_at=completed_at,
        error=row.get("error"),
        result=result,
        source=source,
        clip_duration=row.get("clip_duration"),
        number_of_clips=row.get("number_of_clips"),
        user_id=row.get("user_id"),
    )


class PostgresJobStore:
    """PostgreSQL-backed persistent Job store with connection management."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._init_schema()

    def _connect(self) -> psycopg.Connection[Any]:
        """Create a new PostgreSQL connection."""
        return psycopg.connect(self.database_url)

    def _init_schema(self) -> None:
        """Run schema migrations on startup."""
        with psycopg.connect(self.database_url) as conn:
            run_postgres_migrations(conn)

    def insert(self, job: JobRecord) -> None:
        """Insert a new JobRecord."""
        params = _job_to_params(job)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(_INSERT_SQL, params)
            conn.commit()

    def get(self, job_id: str) -> Optional[JobRecord]:
        """Fetch job by unique job_id."""
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(_SELECT_SQL, (job_id,))
                row = cur.fetchone()
        if not row:
            return None
        return _row_to_job(row)

    def list_by_user(self, user_id: Optional[str] = None) -> List[JobRecord]:
        """List jobs optionally filtered by user_id."""
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                if user_id:
                    cur.execute(_SELECT_BY_USER_SQL, (user_id,))
                else:
                    cur.execute(_SELECT_ALL_SQL)
                rows = cur.fetchall()
        return [_row_to_job(r) for r in rows]

    def delete(self, job_id: str) -> bool:
        """Delete job by job_id."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(_DELETE_SQL, (job_id,))
                rc = cur.rowcount
            conn.commit()
            return rc > 0

    def update(self, job: JobRecord) -> None:
        """Update mutable fields of a JobRecord."""
        params = (
            job.status.value,
            job.progress_percent,
            job.message,
            job.started_at,
            job.completed_at,
            job.error,
            job.result.model_dump_json() if job.result else None,
            job.user_id,
            getattr(job, "retry_count", 0),
            getattr(job, "queue_name", None),
            job.job_id,
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(_UPDATE_SQL, params)
            conn.commit()

    def upsert(self, job: JobRecord) -> None:
        """Upsert a JobRecord."""
        params = _job_to_params(job)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(_UPSERT_SQL, params)
            conn.commit()
