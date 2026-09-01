"""PostgreSQL storage layer for refresh tokens and revoked access-token JTI blocklist.

Provides token rotation, replay-attack detection, and access-token revocation
for production-grade JWT authentication using a PostgreSQL backend.
"""

from datetime import datetime, timezone
import logging
from typing import Any, List, Optional

import psycopg
from psycopg.rows import dict_row

from app.services.db_migrations import run_postgres_migrations

logger = logging.getLogger(__name__)


class PostgresTokenStore:
    """PostgreSQL-backed storage for refresh tokens and JTI revocation list."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._init_schema()

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.database_url)

    def _init_schema(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            run_postgres_migrations(conn)

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
        VALUES (%s, %s, %s, %s, FALSE, %s, %s, %s);
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (token_id, user_id, token_hash, expires_at, now, session_id, user_agent))
            conn.commit()

    def get_refresh_token(self, token_id: str) -> Optional[dict[str, Any]]:
        """Retrieve a refresh token record by token_id. Returns None if not found."""
        sql = "SELECT * FROM refresh_tokens WHERE token_id = %s;"
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, (token_id,))
                row = cur.fetchone()
        if row is None:
            return None

        expires_at = row["expires_at"]
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        created_at = row["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        if created_at is not None and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        return {
            "token_id": row["token_id"],
            "user_id": row["user_id"],
            "token_hash": row["token_hash"],
            "expires_at": expires_at,
            "revoked": bool(row["revoked"]),
            "created_at": created_at,
            "session_id": row.get("session_id"),
            "user_agent": row.get("user_agent"),
        }

    def revoke_refresh_token(self, token_id: str) -> None:
        """Mark a specific refresh token as revoked."""
        sql = "UPDATE refresh_tokens SET revoked = TRUE WHERE token_id = %s;"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (token_id,))
            conn.commit()

    def revoke_all_user_tokens(self, user_id: str) -> None:
        """Revoke all refresh tokens for a user (logout-all)."""
        sql = "UPDATE refresh_tokens SET revoked = TRUE WHERE user_id = %s;"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (user_id,))
            conn.commit()

    def list_active_sessions(self, user_id: str) -> List[dict[str, Any]]:
        """Return non-revoked, non-expired refresh token records for a user."""
        now = datetime.now(timezone.utc)
        sql = """
        SELECT token_id, user_id, expires_at, created_at, session_id, user_agent
        FROM refresh_tokens
        WHERE user_id = %s AND revoked = FALSE AND expires_at > %s
        ORDER BY created_at DESC;
        """
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, (user_id, now))
                rows = cur.fetchall()

        results = []
        for r in rows:
            expires_at = r["expires_at"]
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at)
            if expires_at is not None and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            created_at = r["created_at"]
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at)
            if created_at is not None and created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            results.append({
                "token_id": r["token_id"],
                "user_id": r["user_id"],
                "expires_at": expires_at,
                "created_at": created_at,
                "session_id": r.get("session_id"),
                "user_agent": r.get("user_agent"),
            })
        return results

    # ------------------------------------------------------------------
    # Access Token JTI Revocation (blocklist)
    # ------------------------------------------------------------------

    def revoke_access_token(self, jti: str, expires_at: datetime) -> None:
        """Add an access token JTI to the revocation blocklist."""
        now = datetime.now(timezone.utc)
        sql = """
        INSERT INTO revoked_tokens (jti, revoked_at, expires_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (jti) DO NOTHING;
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (jti, now, expires_at))
            conn.commit()

    def is_access_token_revoked(self, jti: str) -> bool:
        """Check whether an access token JTI is in the revocation blocklist."""
        sql = "SELECT 1 FROM revoked_tokens WHERE jti = %s;"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (jti,))
                return cur.fetchone() is not None

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def cleanup_expired_tokens(self) -> int:
        """Delete expired refresh and revoked access tokens. Returns rows removed."""
        now = datetime.now(timezone.utc)
        removed = 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM refresh_tokens WHERE expires_at <= %s;", (now,))
                removed += cur.rowcount
                cur.execute("DELETE FROM revoked_tokens WHERE expires_at <= %s;", (now,))
                removed += cur.rowcount
            conn.commit()
        return removed
