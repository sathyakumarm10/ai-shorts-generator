"""Unified Database Configuration, Store Abstractions, and Health Diagnostics.

Provides multi-backend database support (PostgreSQL + SQLite), connection pooling,
protocol definitions for persistence stores, and diagnostics.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import logging
import os
from pathlib import Path
import time
from typing import Any, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class DatabaseBackend(str, Enum):
    """Supported database persistence backends."""

    POSTGRESQL = "postgresql"
    SQLITE = "sqlite"


@dataclass
class DatabaseConfig:
    """Database configuration parsed from environment variables."""

    backend: DatabaseBackend = DatabaseBackend.SQLITE
    configured_backend: str = "sqlite"
    database_url: Optional[str] = None
    postgres_host: Optional[str] = None
    postgres_port: int = 5432
    postgres_db: Optional[str] = None
    postgres_user: Optional[str] = None
    postgres_password: Optional[str] = None
    sqlite_job_db_path: str = "data/jobs.sqlite3"
    sqlite_user_db_path: str = "data/users.sqlite3"
    pool_min_size: int = 2
    pool_max_size: int = 10
    connect_timeout_seconds: float = 5.0
    enable_local_fallback: bool = True

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        """Load database configuration from environment variables."""
        raw_backend = os.environ.get("DATABASE_BACKEND", "").strip().lower()
        db_url = os.environ.get("DATABASE_URL", "").strip() or None

        # Determine target backend
        if raw_backend in ("postgres", "postgresql"):
            target_backend = DatabaseBackend.POSTGRESQL
            configured = "postgresql"
        elif raw_backend == "sqlite":
            target_backend = DatabaseBackend.SQLITE
            configured = "sqlite"
        elif db_url and (db_url.startswith("postgres://") or db_url.startswith("postgresql://")):
            target_backend = DatabaseBackend.POSTGRESQL
            configured = "postgresql"
        else:
            target_backend = DatabaseBackend.SQLITE
            configured = "sqlite"

        # Resolve SQLite default paths
        default_dir = Path(__file__).resolve().parent.parent.parent / "data"
        job_db_path = os.environ.get("JOB_DB_PATH", str(default_dir / "jobs.sqlite3"))
        user_db_path = os.environ.get("USER_DB_PATH", str(default_dir / "users.sqlite3"))

        pg_host = os.environ.get("POSTGRES_HOST", "localhost").strip() or None
        pg_port_str = os.environ.get("POSTGRES_PORT", "5432").strip()
        pg_port = int(pg_port_str) if pg_port_str.isdigit() else 5432
        pg_db = os.environ.get("POSTGRES_DB", "ai_shorts_db").strip() or None
        pg_user = os.environ.get("POSTGRES_USER", "postgres").strip() or None
        pg_password = os.environ.get("POSTGRES_PASSWORD", "").strip() or None

        # Build postgres database_url if individual postgres vars provided without full URL
        if target_backend == DatabaseBackend.POSTGRESQL and not db_url and pg_host:
            auth = f"{pg_user}:{pg_password}@" if pg_user and pg_password else (f"{pg_user}@" if pg_user else "")
            db_url = f"postgresql://{auth}{pg_host}:{pg_port}/{pg_db or 'ai_shorts_db'}"

        pool_min = int(os.environ.get("DB_POOL_MIN_SIZE", "2"))
        pool_max = int(os.environ.get("DB_POOL_MAX_SIZE", "10"))
        timeout = float(os.environ.get("DB_CONNECT_TIMEOUT", "5.0"))
        fallback = os.environ.get("DB_ENABLE_LOCAL_FALLBACK", "true").strip().lower() in ("true", "1", "yes")

        return cls(
            backend=target_backend,
            configured_backend=configured,
            database_url=db_url,
            postgres_host=pg_host,
            postgres_port=pg_port,
            postgres_db=pg_db,
            postgres_user=pg_user,
            postgres_password=pg_password,
            sqlite_job_db_path=job_db_path,
            sqlite_user_db_path=user_db_path,
            pool_min_size=pool_min,
            pool_max_size=pool_max,
            connect_timeout_seconds=timeout,
            enable_local_fallback=fallback,
        )


@dataclass
class DatabaseDiagnosticsReport:
    """Diagnostic report describing active database status and connectivity."""

    backend: str
    configured_backend: str
    connected: bool
    database_name: str
    host: Optional[str]
    port: Optional[int]
    migration_version: int
    latency_ms: float
    local_fallback_active: bool
    error: Optional[str] = None


@runtime_checkable
class JobStoreBase(Protocol):
    """Protocol defining the interface for Job persistence stores."""

    def insert(self, job: Any) -> None:
        ...

    def get(self, job_id: str) -> Optional[Any]:
        ...

    def list_by_user(self, user_id: Optional[str] = None) -> List[Any]:
        ...

    def update(self, job: Any) -> None:
        ...

    def delete(self, job_id: str) -> bool:
        ...

    def upsert(self, job: Any) -> None:
        ...


@runtime_checkable
class UserStoreBase(Protocol):
    """Protocol defining the interface for User persistence stores."""

    def create(self, user: Any) -> Any:
        ...

    def get_by_id(self, user_id: str) -> Optional[Any]:
        ...

    def get_by_email(self, email: str) -> Optional[Any]:
        ...

    def list_all(self) -> List[Any]:
        ...


# ---------------------------------------------------------------------------
# Global Config Instance
# ---------------------------------------------------------------------------
default_db_config = DatabaseConfig.from_env()


def get_database_report(config: Optional[DatabaseConfig] = None) -> DatabaseDiagnosticsReport:
    """Run an active connectivity probe and return database diagnostics."""
    cfg = config or DatabaseConfig.from_env()
    t0 = time.perf_counter()

    if cfg.backend == DatabaseBackend.POSTGRESQL and cfg.database_url:
        try:
            import psycopg

            # Probe connection
            with psycopg.connect(cfg.database_url, connect_timeout=int(cfg.connect_timeout_seconds)) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                    cur.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations;")
                    row = cur.fetchone()
                    migration_ver = row[0] if row else 0

            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            db_name = cfg.postgres_db or "postgres"
            if "/" in cfg.database_url:
                db_name = cfg.database_url.rsplit("/", 1)[-1].split("?")[0]

            return DatabaseDiagnosticsReport(
                backend="postgresql",
                configured_backend=cfg.configured_backend,
                connected=True,
                database_name=db_name,
                host=cfg.postgres_host,
                port=cfg.postgres_port,
                migration_version=migration_ver,
                latency_ms=latency_ms,
                local_fallback_active=False,
                error=None,
            )
        except Exception as exc:
            err = str(exc)
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            logger.warning("PostgreSQL health probe failed: %s", exc)
            return DatabaseDiagnosticsReport(
                backend="postgresql",
                configured_backend=cfg.configured_backend,
                connected=False,
                database_name=cfg.postgres_db or "postgres",
                host=cfg.postgres_host,
                port=cfg.postgres_port,
                migration_version=0,
                latency_ms=latency_ms,
                local_fallback_active=cfg.enable_local_fallback,
                error=err,
            )

    # SQLite diagnostic probe
    try:
        import sqlite3
        conn = sqlite3.connect(cfg.sqlite_job_db_path)
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations';")
        has_migrations = cur.fetchone()
        migration_ver = 0
        if has_migrations:
            cur.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations;")
            row = cur.fetchone()
            migration_ver = row[0] if row else 0
        conn.close()

        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        return DatabaseDiagnosticsReport(
            backend="sqlite",
            configured_backend=cfg.configured_backend,
            connected=True,
            database_name=Path(cfg.sqlite_job_db_path).name,
            host="localhost",
            port=None,
            migration_version=migration_ver,
            latency_ms=latency_ms,
            local_fallback_active=False,
            error=None,
        )
    except Exception as exc:
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        return DatabaseDiagnosticsReport(
            backend="sqlite",
            configured_backend=cfg.configured_backend,
            connected=False,
            database_name=Path(cfg.sqlite_job_db_path).name,
            host="localhost",
            port=None,
            migration_version=0,
            latency_ms=latency_ms,
            local_fallback_active=False,
            error=str(exc),
        )


def create_job_store(
    config: Optional[DatabaseConfig] = None,
    db_path: Optional[str] = None,
) -> JobStoreBase:
    """Create a configured JobStore instance with automatic local fallback if PostgreSQL fails."""
    from app.services.job_sqlite import SQLiteJobStore

    if db_path is not None:
        if db_path.startswith("postgres://") or db_path.startswith("postgresql://"):
            from app.services.job_postgres import PostgresJobStore
            return PostgresJobStore(database_url=db_path)
        return SQLiteJobStore(db_path=db_path)

    cfg = config or DatabaseConfig.from_env()
    if cfg.backend == DatabaseBackend.POSTGRESQL and cfg.database_url:
        try:
            from app.services.job_postgres import PostgresJobStore
            return PostgresJobStore(database_url=cfg.database_url)
        except Exception as exc:
            if cfg.enable_local_fallback:
                logger.warning(
                    "Failed to connect to PostgreSQL job store (%s). Falling back to SQLite (%s)",
                    exc,
                    cfg.sqlite_job_db_path,
                )
                return SQLiteJobStore(db_path=cfg.sqlite_job_db_path)
            raise

    return SQLiteJobStore(db_path=cfg.sqlite_job_db_path)


def create_user_store(
    config: Optional[DatabaseConfig] = None,
    db_path: Optional[str] = None,
) -> UserStoreBase:
    """Create a configured UserStore instance with automatic local fallback if PostgreSQL fails."""
    from app.services.user_sqlite import SQLiteUserStore

    if db_path is not None:
        if db_path.startswith("postgres://") or db_path.startswith("postgresql://"):
            from app.services.user_postgres import PostgresUserStore
            return PostgresUserStore(database_url=db_path)
        return SQLiteUserStore(db_path=db_path)

    cfg = config or DatabaseConfig.from_env()
    if cfg.backend == DatabaseBackend.POSTGRESQL and cfg.database_url:
        try:
            from app.services.user_postgres import PostgresUserStore
            return PostgresUserStore(database_url=cfg.database_url)
        except Exception as exc:
            if cfg.enable_local_fallback:
                logger.warning(
                    "Failed to connect to PostgreSQL user store (%s). Falling back to SQLite (%s)",
                    exc,
                    cfg.sqlite_user_db_path,
                )
                return SQLiteUserStore(db_path=cfg.sqlite_user_db_path)
            raise

    return SQLiteUserStore(db_path=cfg.sqlite_user_db_path)


@runtime_checkable
class TokenStoreBase(Protocol):
    """Protocol defining the interface for Token persistence stores (refresh + JTI revocation)."""

    def store_refresh_token(
        self,
        token_id: str,
        user_id: str,
        token_hash: str,
        expires_at: Any,
        session_id: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        ...

    def get_refresh_token(self, token_id: str) -> Optional[Any]:
        ...

    def revoke_refresh_token(self, token_id: str) -> None:
        ...

    def revoke_all_user_tokens(self, user_id: str) -> None:
        ...

    def list_active_sessions(self, user_id: str) -> List[Any]:
        ...

    def revoke_access_token(self, jti: str, expires_at: Any) -> None:
        ...

    def is_access_token_revoked(self, jti: str) -> bool:
        ...

    def cleanup_expired_tokens(self) -> int:
        ...


def create_token_store(
    config: Optional[DatabaseConfig] = None,
    db_path: Optional[str] = None,
) -> TokenStoreBase:
    """Create a configured TokenStore instance with automatic local fallback if PostgreSQL fails."""
    from app.services.token_store_sqlite import SQLiteTokenStore

    if db_path is not None:
        if db_path.startswith("postgres://") or db_path.startswith("postgresql://"):
            from app.services.token_store_postgres import PostgresTokenStore
            return PostgresTokenStore(database_url=db_path)
        return SQLiteTokenStore(db_path=db_path)

    cfg = config or DatabaseConfig.from_env()
    if cfg.backend == DatabaseBackend.POSTGRESQL and cfg.database_url:
        try:
            from app.services.token_store_postgres import PostgresTokenStore
            return PostgresTokenStore(database_url=cfg.database_url)
        except Exception as exc:
            if cfg.enable_local_fallback:
                logger.warning(
                    "Failed to connect to PostgreSQL token store (%s). Falling back to SQLite (%s)",
                    exc,
                    cfg.sqlite_user_db_path,
                )
                return SQLiteTokenStore(db_path=cfg.sqlite_user_db_path)
            raise

    return SQLiteTokenStore(db_path=cfg.sqlite_user_db_path)
