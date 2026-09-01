"""Authentication service providing PBKDF2-SHA256 password hashing and JWT issuance/verification.

Implements token creation, validation, user registration, and authentication dependencies.
"""

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import time
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.models import TokenResponse, User, UserCreate, UserLogin, UserResponse
from app.services.db import UserStoreBase, create_user_store
from app.services.user_sqlite import SQLiteUserStore

_DEFAULT_DB_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_DEFAULT_DB_PATH = os.environ.get("USER_DB_PATH", str(_DEFAULT_DB_DIR / "users.sqlite3"))

AUTH_JWT_SECRET = os.environ.get("AUTH_JWT_SECRET", "dev-insecure-secret-key-change-in-production-1234567890")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # Default 24h
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


def create_jwt_token(payload: Dict[str, Any], secret: str = AUTH_JWT_SECRET, expires_in_seconds: Optional[int] = None) -> str:
    """Create a signed HMAC-SHA256 JWT token."""
    header = {"alg": "HS256", "typ": "JWT"}
    exp_seconds = expires_in_seconds if expires_in_seconds is not None else ACCESS_TOKEN_EXPIRE_MINUTES * 60
    full_payload = {
        **payload,
        "exp": int(time.time() + exp_seconds),
        "iat": int(time.time()),
    }
    h_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=").decode()
    p_b64 = base64.urlsafe_b64encode(json.dumps(full_payload).encode()).rstrip(b"=").decode()
    signing_input = f"{h_b64}.{p_b64}".encode()
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    s_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{h_b64}.{p_b64}.{s_b64}"


def decode_jwt_token(token: str, secret: str = AUTH_JWT_SECRET) -> Optional[Dict[str, Any]]:
    """Verify and decode a JWT token, returning the payload if valid and unexpired."""
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
        return payload
    except Exception:
        return None


class AuthService:
    """Provides user registration, credential verification, and token management."""

    def __init__(self, user_store: Optional[UserStoreBase] = None) -> None:
        self.user_store = user_store or create_user_store()

    def register_user(self, data: UserCreate) -> TokenResponse:
        """Register a new user account and return an access token."""
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
            created_at=now,
            updated_at=now,
        )
        self.user_store.create(new_user)

        expires_seconds = ACCESS_TOKEN_EXPIRE_MINUTES * 60
        token = create_jwt_token(
            payload={"sub": new_user.user_id, "email": new_user.email},
            expires_in_seconds=expires_seconds,
        )

        return TokenResponse(
            access_token=token,
            token_type="bearer",
            expires_in=expires_seconds,
            user=UserResponse(
                user_id=new_user.user_id,
                email=new_user.email,
                created_at=new_user.created_at,
            ),
        )

    def authenticate_user(self, data: UserLogin) -> TokenResponse:
        """Verify user credentials and return an access token."""
        user = self.user_store.get_by_email(data.email)
        if user is None or not verify_password(data.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password.",
            )

        expires_seconds = ACCESS_TOKEN_EXPIRE_MINUTES * 60
        token = create_jwt_token(
            payload={"sub": user.user_id, "email": user.email},
            expires_in_seconds=expires_seconds,
        )

        return TokenResponse(
            access_token=token,
            token_type="bearer",
            expires_in=expires_seconds,
            user=UserResponse(
                user_id=user.user_id,
                email=user.email,
                created_at=user.created_at,
            ),
        )

    def get_user_from_token(self, token: str) -> Optional[User]:
        """Decode token and retrieve user from store."""
        payload = decode_jwt_token(token)
        if not payload or not payload.get("sub"):
            return None
        return self.user_store.get_by_id(payload["sub"])


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
            detail="Invalid or expired authentication token.",
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
