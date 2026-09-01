"""PostgreSQL persistence store for User records.

Provides secure, thread-safe user management with case-insensitive email matching,
unique constraints, and schema migration support.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Optional

import psycopg
from psycopg.rows import dict_row

from app.models import User
from app.services.db_migrations import run_postgres_migrations

logger = logging.getLogger(__name__)

_INSERT_USER_SQL = """\
INSERT INTO users (user_id, email, password_hash, created_at, updated_at)
VALUES (%s, %s, %s, %s, %s);
"""

_SELECT_BY_ID_SQL = "SELECT * FROM users WHERE user_id = %s;"
_SELECT_BY_EMAIL_SQL = "SELECT * FROM users WHERE lower(email) = lower(%s);"


def _row_to_user(row: Any) -> User:
    """Map PostgreSQL dict row to User model."""
    created_at = row["created_at"]
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    updated_at = row["updated_at"]
    if isinstance(updated_at, str):
        updated_at = datetime.fromisoformat(updated_at)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)

    return User(
        user_id=row["user_id"],
        email=row["email"],
        password_hash=row["password_hash"],
        created_at=created_at,
        updated_at=updated_at,
    )


class PostgresUserStore:
    """PostgreSQL-backed storage for User entities."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._init_schema()

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.database_url)

    def _init_schema(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            run_postgres_migrations(conn)

    def create(self, user: User) -> User:
        """Insert a new user record. Raises psycopg.IntegrityError on unique violation."""
        params = (
            user.user_id,
            user.email.strip().lower(),
            user.password_hash,
            user.created_at,
            user.updated_at,
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(_INSERT_USER_SQL, params)
            conn.commit()
        return user

    def get_by_id(self, user_id: str) -> Optional[User]:
        """Fetch user by unique user_id."""
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(_SELECT_BY_ID_SQL, (user_id,))
                row = cur.fetchone()
        return _row_to_user(row) if row else None

    def get_by_email(self, email: str) -> Optional[User]:
        """Fetch user by case-insensitive email address."""
        clean_email = email.strip().lower()
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(_SELECT_BY_EMAIL_SQL, (clean_email,))
                row = cur.fetchone()
        return _row_to_user(row) if row else None
