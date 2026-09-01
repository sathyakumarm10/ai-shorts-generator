"""Authentication service providing PBKDF2-SHA256 password hashing, JWT issuance,
refresh token rotation, replay-attack detection, JTI revocation, and RBAC authorization.

Implements token creation, validation, user registration, refresh flows, sessions, and security dependencies.
"""

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import secrets
import time
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.models import (
    RefreshTokenRequest,
    SessionResponse,
    TokenResponse,
    User,
    UserCreate,
    UserLogin,
    UserResponse,
    UserRole,
)
from app.services.db import (
    TokenStoreBase,
    UserStoreBase,
    create_token_store,
    create_user_store,
)

logger = logging.getLogger(__name__)

_DEFAULT_DB_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_DEFAULT_DB_PATH = os.environ.get("USER_DB_PATH", str(_DEFAULT_DB_DIR / "users.sqlite3"))

AUTH_JWT_SECRET = os.environ.get("AUTH_JWT_SECRET", "dev-insecure-secret-key-change-in-production-1234567890")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # Default 24h
REFRESH_TOKEN_EXPIRE_DAYS = int(os.environ.get("REFRESH_TOKEN_EXPIRE_DAYS", "30"))  # Default 30 days
PBKDF2_ITERATIONS = int(os.environ.get("PBKDF2_ITERATIONS", "100000"))

security_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Hash password using PBKDF2-SHA256 with 16-byte cryptographically secure random salt."""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored PBKDF2-SHA256 hash using constant-time comparison."""
    try:
        parts = stored_hash.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected_dk = bytes.fromhex(parts[3])
        actual_dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual_dk, expected_dk)
    except Exception:
        return False


def create_jwt_token(
    payload: Dict[str, Any],
    secret: str = AUTH_JWT_SECRET,
    expires_in_seconds: Optional[int] = None,
    jti: Optional[str] = None,
) -> str:
    """Create a signed HMAC-SHA256 JWT token with unique JTI claim for revocation tracking."""
    header = {"alg": "HS256", "typ": "JWT"}
    exp_seconds = expires_in_seconds if expires_in_seconds is not None else ACCESS_TOKEN_EXPIRE_MINUTES * 60
    token_jti = jti or str(uuid4())
    full_payload = {
        **payload,
        "jti": token_jti,
        "exp": int(time.time() + exp_seconds),
        "iat": int(time.time()),
    }
    h_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=").decode()
    p_b64 = base64.urlsafe_b64encode(json.dumps(full_payload).encode()).rstrip(b"=").decode()
    signing_input = f"{h_b64}.{p_b64}".encode()
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    s_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{h_b64}.{p_b64}.{s_b64}"


def decode_jwt_token(
    token: str,
    secret: str = AUTH_JWT_SECRET,
    token_store: Optional[TokenStoreBase] = None,
) -> Optional[Dict[str, Any]]:
    """Verify and decode a JWT token, ensuring signature validity, unexpired time, and non-revoked JTI."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        h_b64, p_b64, s_b64 = parts
        signing_input = f"{h_b64}.{p_b64}".encode()
        expected_sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
        actual_sig = base64.urlsafe_b64decode(s_b64 + "=" * (-len(s_b64) % 4))
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

        payload_bytes = base64.urlsafe_b64decode(p_b64 + "=" * (-len(p_b64) % 4))
        payload = json.loads(payload_bytes.decode())
        exp = payload.get("exp")
        if exp is not None and time.time() > exp:
            return None

        # Check JTI blocklist if token store is provided
        jti = payload.get("jti")
        if jti and token_store is not None:
            if token_store.is_access_token_revoked(jti):
                return None

        return payload
    except Exception:
        return None


def generate_refresh_token_pair() -> tuple[str, str, str]:
    """Generate a cryptographically secure refresh token string, ID, and hash.

    Returns (full_token_str, token_id, token_hash).
    Format: rt_<uuid>_<random_secret>
    """
    token_id = str(uuid4())
    raw_secret = secrets.token_urlsafe(32)
    full_token = f"rt_{token_id}_{raw_secret}"
    token_hash = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()
    return full_token, token_id, token_hash


def parse_refresh_token(token_str: str) -> Optional[tuple[str, str]]:
    """Parse a refresh token string into (token_id, raw_secret). Returns None if format invalid."""
    if not token_str or not token_str.startswith("rt_"):
        return None
    parts = token_str.split("_", 2)
    if len(parts) != 3:
        return None
    return parts[1], parts[2]


class AuthService:
    """Provides user registration, credential verification, token rotation, and revocation management."""

    def __init__(
        self,
        user_store: Optional[UserStoreBase] = None,
        token_store: Optional[TokenStoreBase] = None,
    ) -> None:
        self.user_store = user_store or create_user_store()
        self.token_store = token_store or create_token_store()

    def register_user(
        self,
        data: UserCreate,
        user_agent: Optional[str] = None,
    ) -> TokenResponse:
        """Register a new user account and issue both access and refresh tokens."""
        existing = self.user_store.get_by_email(data.email)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this email address already exists.",
            )

        now = datetime.now(timezone.utc)
        user_id = str(uuid4())
        pwd_hash = hash_password(data.password)

        new_user = User(
            user_id=user_id,
            email=data.email,
            password_hash=pwd_hash,
            role=data.role or UserRole.USER,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self.user_store.create(new_user)

        return self._issue_tokens_for_user(new_user, user_agent=user_agent)

    def authenticate_user(
        self,
        data: UserLogin,
        user_agent: Optional[str] = None,
    ) -> TokenResponse:
        """Verify user credentials and return an access and refresh token pair."""
        user = self.user_store.get_by_email(data.email)
        if user is None or not verify_password(data.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password.",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is inactive or suspended.",
            )

        return self._issue_tokens_for_user(user, user_agent=user_agent)

    def _issue_tokens_for_user(
        self,
        user: User,
        session_id: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> TokenResponse:
        """Internal helper to create and store access + refresh tokens."""
        access_expires_seconds = ACCESS_TOKEN_EXPIRE_MINUTES * 60
        refresh_expires_seconds = REFRESH_TOKEN_EXPIRE_DAYS * 86400
        now = datetime.now(timezone.utc)
        refresh_expires_at = datetime.fromtimestamp(now.timestamp() + refresh_expires_seconds, tz=timezone.utc)

        # Create access token with unique JTI
        jti = str(uuid4())
        access_token = create_jwt_token(
            payload={
                "sub": user.user_id,
                "email": user.email,
                "role": user.role.value if hasattr(user.role, "value") else str(user.role),
            },
            expires_in_seconds=access_expires_seconds,
            jti=jti,
        )

        # Create refresh token and store hash
        full_refresh_token, token_id, token_hash = generate_refresh_token_pair()
        sid = session_id or str(uuid4())
        self.token_store.store_refresh_token(
            token_id=token_id,
            user_id=user.user_id,
            token_hash=token_hash,
            expires_at=refresh_expires_at,
            session_id=sid,
            user_agent=user_agent,
        )

        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in=access_expires_seconds,
            refresh_token=full_refresh_token,
            refresh_expires_in=refresh_expires_seconds,
            user=UserResponse(
                user_id=user.user_id,
                email=user.email,
                role=user.role,
                is_active=user.is_active,
                created_at=user.created_at,
            ),
        )

    def refresh_tokens(
        self,
        refresh_token_str: str,
        user_agent: Optional[str] = None,
    ) -> TokenResponse:
        """Rotate refresh token and issue new access/refresh token pair.

        Detects replay attacks: if a revoked token is used, all tokens for the user
        are revoked immediately to mitigate token theft.
        """
        parsed = parse_refresh_token(refresh_token_str)
        if not parsed:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token format.",
            )

        token_id, raw_secret = parsed
        record = self.token_store.get_refresh_token(token_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token not found or invalid.",
            )

        user_id = record["user_id"]
        user = self.user_store.get_by_id(user_id)
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account not found or inactive.",
            )

        # REPLAY ATTACK DETECTION
        if record["revoked"]:
            logger.warning(
                "Refresh token reuse/replay attack detected for user %s (token_id: %s)! Invalidating all sessions.",
                user_id,
                token_id,
            )
            self.token_store.revoke_all_user_tokens(user_id)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token reuse detected. All sessions have been terminated for security.",
            )

        # Check expiration
        expires_at = record["expires_at"]
        if expires_at is not None:
            now = datetime.now(timezone.utc)
            if now > expires_at:
                self.token_store.revoke_refresh_token(token_id)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Refresh token has expired. Please log in again.",
                )

        # Verify hash match using constant-time comparison
        expected_hash = record["token_hash"]
        actual_hash = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(expected_hash, actual_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token signature.",
            )

        # ROTATION: Revoke the old token
        self.token_store.revoke_refresh_token(token_id)

        # Issue new token pair preserving the session_id
        session_id = record.get("session_id")
        return self._issue_tokens_for_user(
            user=user,
            session_id=session_id,
            user_agent=user_agent or record.get("user_agent"),
        )

    def logout_user(
        self,
        raw_access_token: Optional[str] = None,
        current_user: Optional[User] = None,
    ) -> None:
        """Revoke current access token JTI and revoke all active refresh tokens for the user."""
        if raw_access_token:
            payload = decode_jwt_token(raw_access_token, token_store=None)
            if payload and "jti" in payload:
                jti = payload["jti"]
                exp = payload.get("exp", int(time.time()) + 86400)
                expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
                self.token_store.revoke_access_token(jti, expires_at)

        if current_user:
            self.token_store.revoke_all_user_tokens(current_user.user_id)

    def get_user_from_token(self, token: str) -> Optional[User]:
        """Decode token, verify JTI is not on revocation blocklist, and retrieve active user."""
        payload = decode_jwt_token(token, token_store=self.token_store)
        if not payload or not payload.get("sub"):
            return None
        user = self.user_store.get_by_id(payload["sub"])
        if user is None or not user.is_active:
            return None
        return user

    def list_user_sessions(self, user_id: str) -> List[SessionResponse]:
        """List all active non-revoked sessions for a user."""
        sessions = self.token_store.list_active_sessions(user_id)
        return [
            SessionResponse(
                token_id=s["token_id"],
                created_at=s["created_at"],
                expires_at=s["expires_at"],
                user_agent=s.get("user_agent"),
            )
            for s in sessions
        ]

    def revoke_session(self, user_id: str, token_id: str) -> bool:
        """Revoke a specific session if owned by the user."""
        record = self.token_store.get_refresh_token(token_id)
        if record and record["user_id"] == user_id:
            self.token_store.revoke_refresh_token(token_id)
            return True
        return False


default_auth_service = AuthService()


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
) -> User:
    """FastAPI dependency requiring valid Bearer authentication."""
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Missing Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = default_auth_service.get_user_from_token(credentials.credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or revoked authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
) -> Optional[User]:
    """FastAPI dependency for endpoints that allow optional authentication."""
    if not credentials or not credentials.credentials:
        return None
    return default_auth_service.get_user_from_token(credentials.credentials)


def require_role(required_role: UserRole) -> Callable[..., User]:
    """Role-Based Access Control (RBAC) dependency factory.

    Enforces that the authenticated user possesses the required role (or admin role).
    """

    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        user_role = current_user.role
        if isinstance(user_role, str):
            try:
                user_role = UserRole(user_role)
            except ValueError:
                user_role = UserRole.USER

        # Admin satisfies all role requirements
        if user_role == UserRole.ADMIN:
            return current_user

        if user_role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: '{required_role.value}' role required for this resource.",
            )
        return current_user

    return role_checker


require_admin = require_role(UserRole.ADMIN)
