"""Tests for database migrations, SQLite persistence, and store protocol compliance."""

import sqlite3
import tempfile
import os
from datetime import datetime, timezone
from pathlib import Path
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_temp_db() -> str:
    """Return a path to a fresh temporary SQLite database."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    return path


def _make_job(
    job_id: str = "job-1",
    user_id: str = "user-1",
    status: str = "queued",
) -> "object":
    from app.models import JobRecord, JobStatus

    return JobRecord(
        job_id=job_id,
        user_id=user_id,
        status=JobStatus(status),
        progress_percent=0.0,
        message="Job queued",
        created_at=datetime.now(timezone.utc),
        started_at=None,
        completed_at=None,
        error=None,
        result=None,
        source=None,
    )


def _make_user(
    user_id: str = "user-1",
    email: str = "user@example.com",
) -> "object":
    from app.models import User

    now = datetime.now(timezone.utc)
    return User(
        user_id=user_id,
        email=email,
        password_hash="hashed_password_value",
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Migration tests
# ---------------------------------------------------------------------------


class TestSQLiteMigrations:
    """Verify that the SQLite migration runner is idempotent and additive."""

    def test_migrations_create_schema_migrations_table(self) -> None:
        from app.services.db_migrations import run_sqlite_migrations

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        run_sqlite_migrations(conn)
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations';"
        )
        assert cur.fetchone() is not None, "schema_migrations table must exist"
        conn.close()

    def test_migrations_create_jobs_and_users_tables(self) -> None:
        from app.services.db_migrations import run_sqlite_migrations

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        run_sqlite_migrations(conn)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            ).fetchall()
        }
        assert "jobs" in tables
        assert "users" in tables
        conn.close()

    def test_migrations_are_idempotent(self) -> None:
        """Running migrations twice should not raise and version should not advance."""
        from app.services.db_migrations import run_sqlite_migrations

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        run_sqlite_migrations(conn)
        run_sqlite_migrations(conn)  # second call must succeed without error
        row = conn.execute(
            "SELECT MAX(version) FROM schema_migrations;"
        ).fetchone()
        assert row is not None and row[0] is not None
        version_after_two_runs = row[0]

        run_sqlite_migrations(conn)
        row2 = conn.execute(
            "SELECT MAX(version) FROM schema_migrations;"
        ).fetchone()
        assert row2 is not None and row2[0] == version_after_two_runs
        conn.close()

    def test_migration_version_increases_monotonically(self) -> None:
        from app.services.db_migrations import run_sqlite_migrations

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        run_sqlite_migrations(conn)
        rows = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version;"
        ).fetchall()
        versions = [r[0] for r in rows]
        assert versions == sorted(versions), "Versions must be monotonically increasing"
        assert len(versions) >= 1, "At least one migration must be recorded"
        conn.close()


# ---------------------------------------------------------------------------
# SQLiteJobStore CRUD tests
# ---------------------------------------------------------------------------


class TestSQLiteJobStore:
    """Verify SQLiteJobStore CRUD operations and SQLite-specific behaviour."""

    def _store(self, db_path: str = ":memory:") -> "object":
        from app.services.job_sqlite import SQLiteJobStore

        return SQLiteJobStore(db_path=db_path)

    def test_insert_and_get(self) -> None:
        store = self._store()
        job = _make_job("j-001")
        store.insert(job)
        fetched = store.get("j-001")
        assert fetched is not None
        assert fetched.job_id == "j-001"

    def test_get_nonexistent_returns_none(self) -> None:
        store = self._store()
        assert store.get("nonexistent") is None

    def test_list_by_user(self) -> None:
        store = self._store()
        store.insert(_make_job("j-1", user_id="u-1"))
        store.insert(_make_job("j-2", user_id="u-1"))
        store.insert(_make_job("j-3", user_id="u-2"))
        jobs_u1 = store.list_by_user("u-1")
        assert len(jobs_u1) == 2
        assert all(j.user_id == "u-1" for j in jobs_u1)

    def test_list_all_when_no_user_id(self) -> None:
        store = self._store()
        store.insert(_make_job("j-1", user_id="u-1"))
        store.insert(_make_job("j-2", user_id="u-2"))
        all_jobs = store.list_by_user(None)
        assert len(all_jobs) == 2

    def test_update(self) -> None:
        from app.models import JobStatus

        store = self._store()
        job = _make_job("j-upd")
        store.insert(job)
        job.status = JobStatus.PROCESSING
        job.progress_percent = 50.0
        store.update(job)
        updated = store.get("j-upd")
        assert updated is not None
        assert updated.status == JobStatus.PROCESSING
        assert updated.progress_percent == 50.0

    def test_delete(self) -> None:
        store = self._store()
        store.insert(_make_job("j-del"))
        result = store.delete("j-del")
        assert result is True
        assert store.get("j-del") is None

    def test_delete_nonexistent_returns_false(self) -> None:
        store = self._store()
        assert store.delete("does-not-exist") is False

    def test_upsert_inserts_new(self) -> None:
        store = self._store()
        store.upsert(_make_job("j-new"))
        assert store.get("j-new") is not None

    def test_upsert_updates_existing(self) -> None:
        from app.models import JobStatus

        store = self._store()
        job = _make_job("j-upsert")
        store.insert(job)
        job.status = JobStatus.PROCESSING
        store.upsert(job)
        fetched = store.get("j-upsert")
        assert fetched is not None
        assert fetched.status == JobStatus.PROCESSING


# ---------------------------------------------------------------------------
# SQLiteUserStore tests
# ---------------------------------------------------------------------------


class TestSQLiteUserStore:
    def _store(self, db_path: str = ":memory:") -> "object":
        from app.services.user_sqlite import SQLiteUserStore

        return SQLiteUserStore(db_path=db_path)

    def test_create_and_get_by_id(self) -> None:
        store = self._store()
        user = _make_user()
        created = store.create(user)
        fetched = store.get_by_id(created.user_id)
        assert fetched is not None
        assert fetched.email == "user@example.com"

    def test_get_by_email(self) -> None:
        store = self._store()
        user = _make_user(email="find@example.com")
        store.create(user)
        fetched = store.get_by_email("find@example.com")
        assert fetched is not None
        assert fetched.email == "find@example.com"

    def test_get_by_email_case_insensitive(self) -> None:
        store = self._store()
        store.create(_make_user(user_id="uid-case", email="Case@Example.COM"))
        fetched = store.get_by_email("case@example.com")
        assert fetched is not None

    def test_get_by_nonexistent_id(self) -> None:
        store = self._store()
        assert store.get_by_id("nope") is None

    def test_get_by_nonexistent_email(self) -> None:
        store = self._store()
        assert store.get_by_email("nobody@example.com") is None


# ---------------------------------------------------------------------------
# DatabaseConfig parsing tests
# ---------------------------------------------------------------------------


class TestDatabaseConfig:
    def test_default_is_sqlite(self) -> None:
        from app.services.db import DatabaseConfig, DatabaseBackend

        cfg = DatabaseConfig()
        assert cfg.backend == DatabaseBackend.SQLITE

    def test_from_env_sqlite_explicit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.services.db import DatabaseConfig, DatabaseBackend

        monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        cfg = DatabaseConfig.from_env()
        assert cfg.backend == DatabaseBackend.SQLITE

    def test_from_env_postgres_explicit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.services.db import DatabaseConfig, DatabaseBackend

        monkeypatch.setenv("DATABASE_BACKEND", "postgres")
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
        cfg = DatabaseConfig.from_env()
        assert cfg.backend == DatabaseBackend.POSTGRESQL

    def test_from_env_postgres_inferred_from_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.services.db import DatabaseConfig, DatabaseBackend

        monkeypatch.delenv("DATABASE_BACKEND", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
        cfg = DatabaseConfig.from_env()
        assert cfg.backend == DatabaseBackend.POSTGRESQL

    def test_from_env_builds_url_from_parts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.services.db import DatabaseConfig

        monkeypatch.setenv("DATABASE_BACKEND", "postgres")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("POSTGRES_HOST", "pghost")
        monkeypatch.setenv("POSTGRES_USER", "myuser")
        monkeypatch.setenv("POSTGRES_PASSWORD", "mypass")
        monkeypatch.setenv("POSTGRES_DB", "mydb")
        monkeypatch.setenv("POSTGRES_PORT", "5433")
        cfg = DatabaseConfig.from_env()
        assert cfg.database_url is not None
        assert "pghost" in cfg.database_url
        assert "mydb" in cfg.database_url


# ---------------------------------------------------------------------------
# Store factory (create_job_store / create_user_store) tests
# ---------------------------------------------------------------------------


class TestStoreFactory:
    def test_create_job_store_default_is_sqlite(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.services.db import create_job_store
        from app.services.job_sqlite import SQLiteJobStore

        monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        store = create_job_store(db_path=":memory:")
        assert isinstance(store, SQLiteJobStore)

    def test_create_user_store_default_is_sqlite(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.services.db import create_user_store
        from app.services.user_sqlite import SQLiteUserStore

        store = create_user_store(db_path=":memory:")
        assert isinstance(store, SQLiteUserStore)

    def test_create_job_store_postgres_fallback_on_bad_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services.db import DatabaseConfig, create_job_store
        from app.services.job_sqlite import SQLiteJobStore

        monkeypatch.setenv("DATABASE_BACKEND", "postgres")
        monkeypatch.setenv("DATABASE_URL", "postgresql://invalid_host:9999/bad_db")
        monkeypatch.setenv("DB_ENABLE_LOCAL_FALLBACK", "true")

        # Falls back to SQLite because postgres connection fails
        cfg = DatabaseConfig.from_env()
        cfg.sqlite_job_db_path = ":memory:"
        cfg.enable_local_fallback = True
        store = create_job_store(config=cfg)
        assert isinstance(store, SQLiteJobStore)
