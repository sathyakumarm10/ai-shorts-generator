"""Unit tests for user registration, authentication, password hashing, and JWT tokens."""

from datetime import datetime, timezone
import pytest

from app.models import UserCreate, UserLogin
from app.services.auth_service import (
    AuthService,
    create_jwt_token,
    decode_jwt_token,
    hash_password,
    verify_password,
)
from app.services.user_sqlite import SQLiteUserStore


class TestAuthService:
    def test_password_hashing_and_verification(self):
        pwd = "SecurePassword!123"
        hashed = hash_password(pwd)
        assert hashed.startswith("pbkdf2_sha256$")
        assert verify_password(pwd, hashed) is True
        assert verify_password("WrongPassword", hashed) is False

    def test_jwt_creation_and_decoding(self):
        payload = {"sub": "user-456", "email": "test@example.com"}
        token = create_jwt_token(payload, secret="test-secret-key-12345", expires_in_seconds=3600)
        assert isinstance(token, str)
        decoded = decode_jwt_token(token, secret="test-secret-key-12345")
        assert decoded is not None
        assert decoded["sub"] == "user-456"
        assert decoded["email"] == "test@example.com"

    def test_expired_jwt_rejection(self):
        payload = {"sub": "user-expired"}
        token = create_jwt_token(payload, secret="test-secret-key-12345", expires_in_seconds=-10)
        decoded = decode_jwt_token(token, secret="test-secret-key-12345")
        assert decoded is None

    def test_user_registration_and_login_flow(self, tmp_path):
        db_path = str(tmp_path / "test_users.sqlite3")
        store = SQLiteUserStore(db_path=db_path)
        service = AuthService(user_store=store)

        # Register
        reg_res = service.register_user(UserCreate(email="creator@example.com", password="Password123!"))
        assert reg_res.access_token is not None
        assert reg_res.user.email == "creator@example.com"

        # Duplicate register fails
        with pytest.raises(Exception):
            service.register_user(UserCreate(email="creator@example.com", password="AnotherPassword!"))

        # Login success
        login_res = service.authenticate_user(UserLogin(email="creator@example.com", password="Password123!"))
        assert login_res.access_token is not None
        assert login_res.user.user_id == reg_res.user.user_id

        # Login failure
        with pytest.raises(Exception):
            service.authenticate_user(UserLogin(email="creator@example.com", password="WrongPassword!"))
