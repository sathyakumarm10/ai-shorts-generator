"""Database migration manager for PostgreSQL and SQLite.

Provides additive, idempotent schema versioning and migration execution
across supported database backends.
"""

from datetime import datetime, timezone
import logging
from typing import Any, List, Tuple

logger = logging.getLogger(__name__)

# Migration definitions: (version, migration_name, sqlite_sql_list, postgres_sql_list)
MIGRATIONS: List[Tuple[int, str, List[str], List[str]]] = [
    (
        1,
        "initial_schema",
        [
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id        TEXT PRIMARY KEY,
                email          TEXT UNIQUE NOT NULL,
                password_hash  TEXT NOT NULL,
                created_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id            TEXT PRIMARY KEY,
                status            TEXT NOT NULL,
                progress_percent  REAL NOT NULL DEFAULT 0.0,
                message           TEXT NOT NULL DEFAULT 'Job queued',
                created_at        TEXT NOT NULL,
                started_at        TEXT,
                completed_at      TEXT,
                error             TEXT,
                result_json       TEXT,
                source_json       TEXT,
                clip_duration     INTEGER,
                number_of_clips   INTEGER,
                user_id           TEXT
            );
            """,
        ],
        [
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id        TEXT PRIMARY KEY,
                email          TEXT UNIQUE NOT NULL,
                password_hash  TEXT NOT NULL,
                created_at     TIMESTAMPTZ NOT NULL,
                updated_at     TIMESTAMPTZ NOT NULL
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id            TEXT PRIMARY KEY,
                status            TEXT NOT NULL,
                progress_percent  REAL NOT NULL DEFAULT 0.0,
                message           TEXT NOT NULL DEFAULT 'Job queued',
                created_at        TIMESTAMPTZ NOT NULL,
                started_at        TIMESTAMPTZ,
                completed_at      TIMESTAMPTZ,
                error             TEXT,
                result_json       TEXT,
                source_json       TEXT,
                clip_duration     INTEGER,
                number_of_clips   INTEGER,
                user_id           TEXT
            );
            """,
        ],
    ),
    (
        2,
        "add_queue_metadata_and_indices",
        [
            # SQLite migrations - columns may already exist in older instances, ignore if exists
            """
            CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs(user_id);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
            """,
        ],
        [
            """
            ALTER TABLE jobs ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;
            """,
            """
            ALTER TABLE jobs ADD COLUMN IF NOT EXISTS queue_name TEXT;
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs(user_id);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
            """,
        ],
    ),
]


def run_sqlite_migrations(conn: Any) -> int:
    """Run all pending schema migrations on a SQLite connection.

    Returns the latest applied migration version number.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     INTEGER PRIMARY KEY,
            name        TEXT NOT NULL,
            applied_at  TEXT NOT NULL
        );
        """
    )
    conn.commit()

    cursor.execute("SELECT version FROM schema_migrations ORDER BY version ASC;")
    applied_versions = {row[0] for row in cursor.fetchall()}

    latest_version = max(applied_versions, default=0)

    for version, name, sqlite_sql_list, _ in MIGRATIONS:
        if version not in applied_versions:
            logger.info("Applying SQLite migration %d: %s", version, name)
            for stmt in sqlite_sql_list:
                stmt_clean = stmt.strip()
                if stmt_clean:
                    try:
                        cursor.execute(stmt_clean)
                    except Exception as exc:
                        logger.warning("Migration statement note (%s): %s", name, exc)

            # Check and add columns dynamically for SQLite if needed
            if version == 2:
                _ensure_sqlite_column(conn, "jobs", "retry_count", "INTEGER NOT NULL DEFAULT 0")
                _ensure_sqlite_column(conn, "jobs", "queue_name", "TEXT")
                _ensure_sqlite_column(conn, "jobs", "user_id", "TEXT")

            now_iso = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?);",
                (version, name, now_iso),
            )
            conn.commit()
            latest_version = version

    return latest_version


def _ensure_sqlite_column(conn: Any, table: str, column: str, col_def: str) -> None:
    """Safely check and add a column to a SQLite table if it does not exist."""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table});")
    existing_cols = [row[1] for row in cursor.fetchall()]
    if column not in existing_cols:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def};")
            conn.commit()
        except Exception:
            pass


def run_postgres_migrations(conn: Any) -> int:
    """Run all pending schema migrations on a PostgreSQL connection.

    Returns the latest applied migration version number.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version     INTEGER PRIMARY KEY,
                name        TEXT NOT NULL,
                applied_at  TIMESTAMPTZ NOT NULL
            );
            """
        )
        conn.commit()

        cursor.execute("SELECT version FROM schema_migrations ORDER BY version ASC;")
        applied_versions = {row[0] for row in cursor.fetchall()}

        latest_version = max(applied_versions, default=0)

        for version, name, _, pg_sql_list in MIGRATIONS:
            if version not in applied_versions:
                logger.info("Applying PostgreSQL migration %d: %s", version, name)
                for stmt in pg_sql_list:
                    stmt_clean = stmt.strip()
                    if stmt_clean:
                        cursor.execute(stmt_clean)

                now = datetime.now(timezone.utc)
                cursor.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (%s, %s, %s);",
                    (version, name, now),
                )
                conn.commit()
                latest_version = version

    return latest_version
