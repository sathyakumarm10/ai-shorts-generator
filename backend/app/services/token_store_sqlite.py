"""SQLite storage layer for refresh tokens and revoked access-token JTI blocklist.

Provides token rotation, replay-attack detection, and access-token revocation
for production-grade JWT authentication.
"""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any, List, Optional

from app.services.db_migrations import run_sqlite_migrations


def _str_to_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _dt_to_str(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


class SQLiteTokenStore:
    """Thread-safe SQLite storage for refresh tokens and JTI revocation list."""

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
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        if not self._is_memory:
            conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _connect(self) -> sqlite3.Connection:
        if self._shared_conn is not None:
            return self._shared_conn
        return self._new_connection()

    def _init_schema(self) -> None:
        conn = self._connect()
        run_sqlite_migrations(conn)

    # ------------------------------------------------------------------
    # Refresh Tokens
    # ------------------------------------------------------------------

    def store_refresh_token(
        self,
        token_id: str,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
        session_id: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        """Persist a new hashed refresh token record."""
        now = datetime.now(timezone.utc)
        sql = """
        INSERT INTO refresh_tokens
            (token_id, user_id, token_hash, expires_at, revoked, created_at, session_id, user_agent)
        VALUES (?, ?, ?, ?, 0, ?, ?, ?);
        """
        with self._connect() as conn:
            conn.execute(
                sql,
                (
                    token_id,
                    user_id,
                    token_hash,
                    _dt_to_str(expires_at),
                    _dt_to_str(now),
                    session_id,
                    user_agent,
                ),
            )

    def get_refresh_token(self, token_id: str) -> Optional[dict[str, Any]]:
        """Retrieve a refresh token record by token_id. Returns None if not found."""
        sql = "SELECT * FROM refresh_tokens WHERE token_id = ?;"
        with self._connect() as conn:
            cursor = conn.execute(sql, (token_id,))
            row = cursor.fetchone()
        if row is None:
            return None
        return {
            "token_id": row["token_id"],
            "user_id": row["user_id"],
            "token_hash": row["token_hash"],
            "expires_at": _str_to_dt(row["expires_at"]),
            "revoked": bool(row["revoked"]),
            "created_at": _str_to_dt(row["created_at"]),
            "session_id": row["session_id"],
            "user_agent": row["user_agent"],
        }

    def revoke_refresh_token(self, token_id: str) -> None:
        """Mark a specific refresh token as revoked (prevents future use)."""
        sql = "UPDATE refresh_tokens SET revoked = 1 WHERE token_id = ?;"
        with self._connect() as conn:
            conn.execute(sql, (token_id,))

    def revoke_all_user_tokens(self, user_id: str) -> None:
        """Revoke all refresh tokens for a user (logout-all / security reset)."""
        sql = "UPDATE refresh_tokens SET revoked = 1 WHERE user_id = ?;"
        with self._connect() as conn:
            conn.execute(sql, (user_id,))

    def list_active_sessions(self, user_id: str) -> List[dict[str, Any]]:
        """Return non-revoked, non-expired refresh token records for a user."""
        now_str = _dt_to_str(datetime.now(timezone.utc)) or ""
        sql = """
        SELECT * FROM refresh_tokens
        WHERE user_id = ? AND revoked = 0 AND expires_at > ?
        ORDER BY created_at DESC;
        """
        with self._connect() as conn:
            cursor = conn.execute(sql, (user_id, now_str))
            rows = cursor.fetchall()
        return [
            {
                "token_id": r["token_id"],
                "user_id": r["user_id"],
                "expires_at": _str_to_dt(r["expires_at"]),
                "created_at": _str_to_dt(r["created_at"]),
                "session_id": r["session_id"],
                "user_agent": r["user_agent"],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Access Token JTI Revocation (blocklist)
    # ------------------------------------------------------------------

    def revoke_access_token(self, jti: str, expires_at: datetime) -> None:
        """Add an access token JTI to the revocation blocklist."""
        now = datetime.now(timezone.utc)
        sql = """
        INSERT OR IGNORE INTO revoked_tokens (jti, revoked_at, expires_at)
        VALUES (?, ?, ?);
        """
        with self._connect() as conn:
            conn.execute(sql, (jti, _dt_to_str(now), _dt_to_str(expires_at)))

    def is_access_token_revoked(self, jti: str) -> bool:
        """Check whether an access token JTI is in the revocation blocklist."""
        sql = "SELECT 1 FROM revoked_tokens WHERE jti = ?;"
        with self._connect() as conn:
            cursor = conn.execute(sql, (jti,))
            return cursor.fetchone() is not None

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def cleanup_expired_tokens(self) -> int:
        """Delete expired refresh and revoked access tokens. Returns rows removed."""
        now_str = _dt_to_str(datetime.now(timezone.utc)) or ""
        removed = 0
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM refresh_tokens WHERE expires_at <= ?;", (now_str,)
            )
            removed += cur.rowcount
            cur = conn.execute(
                "DELETE FROM revoked_tokens WHERE expires_at <= ?;", (now_str,)
            )
            removed += cur.rowcount
        return removed
