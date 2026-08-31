"""SQLite storage layer for User persistence.

Provides additive schema creation and CRUD operations for registered user records.
"""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Optional

from app.models import User


_CREATE_USERS_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS users (
    user_id        TEXT PRIMARY KEY,
    email          TEXT UNIQUE NOT NULL,
    password_hash  TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
"""

_INSERT_USER_SQL = """\
INSERT INTO users (user_id, email, password_hash, created_at, updated_at)
VALUES (?, ?, ?, ?, ?);
"""

_SELECT_BY_ID_SQL = "SELECT * FROM users WHERE user_id = ?;"
_SELECT_BY_EMAIL_SQL = "SELECT * FROM users WHERE lower(email) = lower(?);"


def _str_to_dt(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


def _dt_to_str(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        user_id=row["user_id"],
        email=row["email"],
        password_hash=row["password_hash"],
        created_at=_str_to_dt(row["created_at"]) or datetime.now(timezone.utc),
        updated_at=_str_to_dt(row["updated_at"]) or datetime.now(timezone.utc),
    )


class SQLiteUserStore:
    """Thread-safe SQLite storage for User entities."""

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
        conn.execute(_CREATE_USERS_TABLE_SQL)
        conn.commit()

    def create(self, user: User) -> User:
        """Insert a new user record. Raises sqlite3.IntegrityError if email or ID exists."""
        params = (
            user.user_id,
            user.email.strip().lower(),
            user.password_hash,
            _dt_to_str(user.created_at),
            _dt_to_str(user.updated_at),
        )
        with self._connect() as conn:
            conn.execute(_INSERT_USER_SQL, params)
        return user

    def get_by_id(self, user_id: str) -> Optional[User]:
        """Fetch user by unique user_id."""
        with self._connect() as conn:
            cursor = conn.execute(_SELECT_BY_ID_SQL, (user_id,))
            row = cursor.fetchone()
        return _row_to_user(row) if row else None

    def get_by_email(self, email: str) -> Optional[User]:
        """Fetch user by email address (case-insensitive)."""
        clean_email = email.strip().lower()
        with self._connect() as conn:
            cursor = conn.execute(_SELECT_BY_EMAIL_SQL, (clean_email,))
            row = cursor.fetchone()
        return _row_to_user(row) if row else None
