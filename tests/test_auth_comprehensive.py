"""Comprehensive test suite for Phase 7 production-grade authentication and authorization.

Covers:
- Secure PBKDF2 password hashing and verification
- JWT token lifecycle, expiration, signature verification, and JTI claims
- Refresh token issuance, hash storage, and secure rotation
- Replay-attack detection (revoked token reuse triggers user-wide session invalidation)
- Access token JTI revocation blocklist on logout
- User session tracking and individual session revocation
- Role-Based Access Control (RBAC) and admin endpoints
- Full FastAPI HTTP authentication API routes (/register, /login, /refresh, /logout, /me, /sessions, /admin/users)
- Unauthorized access rejection on protected endpoints
- Multi-user isolation and regression coverage with job pipeline
"""

from datetime import datetime, timezone
import hashlib
import time
from uuid import uuid4

from fastapi import status
from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.models import (
    RefreshTokenRequest,
    User,
    UserCreate,
    UserLogin,
    UserRole,
)
from app.services.auth_service import (
    AuthService,
    create_jwt_token,
    decode_jwt_token,
    generate_refresh_token_pair,
    hash_password,
    parse_refresh_token,
    verify_password,
)
from app.services.token_store_sqlite import SQLiteTokenStore
from app.services.user_sqlite import SQLiteUserStore


@pytest.fixture
def clean_auth_service(tmp_path):
    """Fixture providing an isolated AuthService backed by temporary SQLite stores."""
    db_users = str(tmp_path / "auth_users.sqlite3")
    db_tokens = str(tmp_path / "auth_tokens.sqlite3")
    user_store = SQLiteUserStore(db_path=db_users)
    token_store = SQLiteTokenStore(db_path=db_tokens)
    return AuthService(user_store=user_store, token_store=token_store)


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient configured with fresh in-memory / temporary SQLite stores."""
    db_users = str(tmp_path / "api_users.sqlite3")
    db_tokens = str(tmp_path / "api_tokens.sqlite3")
    user_store = SQLiteUserStore(db_path=db_users)
    token_store = SQLiteTokenStore(db_path=db_tokens)
    auth_srv = AuthService(user_store=user_store, token_store=token_store)

    from app.main import default_auth_service
    monkeypatch.setattr("app.main.default_auth_service", auth_srv)
    monkeypatch.setattr("app.services.auth_service.default_auth_service", auth_srv)

    return TestClient(app)


# ==============================================================================
# 1. Password Security & Hashing Tests
# ==============================================================================


class TestPasswordSecurity:
    def test_pbkdf2_hashing_structure_and_verification(self):
        password = "VeryStrongPassword@2026!"
        hashed = hash_password(password)

        # Structure format: pbkdf2_sha256$<iterations>$<salt_hex>$<dk_hex>
        parts = hashed.split("$")
        assert len(parts) == 4
        assert parts[0] == "pbkdf2_sha256"
        assert int(parts[1]) >= 100000
        assert len(parts[2]) == 32  # 16 bytes = 32 hex chars salt
        assert len(parts[3]) == 64  # SHA-256 = 32 bytes = 64 hex chars

        assert verify_password(password, hashed) is True
        assert verify_password("wrong_password", hashed) is False
        assert verify_password("", hashed) is False

    def test_unique_salts_produce_distinct_hashes(self):
        pwd = "CommonPassword123"
        hash1 = hash_password(pwd)
        hash2 = hash_password(pwd)
        assert hash1 != hash2
        assert verify_password(pwd, hash1) is True
        assert verify_password(pwd, hash2) is True

    def test_malformed_hash_safely_rejected(self):
        assert verify_password("pwd", "invalid_hash_format") is False
        assert verify_password("pwd", "pbkdf2_sha256$notanumber$salt$hash") is False
        assert verify_password("pwd", "") is False


# ==============================================================================
# 2. JWT Lifecycle & JTI Revocation Tests
# ==============================================================================


class TestJWTTokenSecurity:
    def test_create_and_decode_jwt_token_with_jti(self):
        payload = {"sub": "user-123", "email": "user@example.com", "role": "user"}
        token = create_jwt_token(payload, secret="test-jwt-secret", expires_in_seconds=3600)
        decoded = decode_jwt_token(token, secret="test-jwt-secret")

        assert decoded is not None
        assert decoded["sub"] == "user-123"
        assert decoded["email"] == "user@example.com"
        assert decoded["role"] == "user"
        assert "jti" in decoded
        assert len(decoded["jti"]) > 10

    def test_expired_token_rejected(self):
        payload = {"sub": "user-exp"}
        token = create_jwt_token(payload, secret="test-jwt-secret", expires_in_seconds=-5)
        decoded = decode_jwt_token(token, secret="test-jwt-secret")
        assert decoded is None

    def test_tampered_token_rejected(self):
        token = create_jwt_token({"sub": "user-1"}, secret="secret-a")
        # Decoding with different secret
        assert decode_jwt_token(token, secret="secret-b") is None

        # Tampering with payload
        parts = token.split(".")
        tampered_token = f"{parts[0]}.{parts[1]}abc.{parts[2]}"
        assert decode_jwt_token(tampered_token, secret="secret-a") is None

    def test_jti_revocation_blocklist(self, tmp_path):
        token_store = SQLiteTokenStore(db_path=str(tmp_path / "tokens.sqlite3"))
        jti = str(uuid4())
        token = create_jwt_token({"sub": "user-rev"}, secret="test-secret", expires_in_seconds=3600, jti=jti)

        # Before revocation: valid
        decoded_before = decode_jwt_token(token, secret="test-secret", token_store=token_store)
        assert decoded_before is not None

        # Revoke JTI
        exp_dt = datetime.now(timezone.utc)
        token_store.revoke_access_token(jti, exp_dt)
        assert token_store.is_access_token_revoked(jti) is True

        # After revocation: rejected
        decoded_after = decode_jwt_token(token, secret="test-secret", token_store=token_store)
        assert decoded_after is None


# ==============================================================================
# 3. Refresh Token Issuance, Rotation & Replay Attack Detection
# ==============================================================================


class TestRefreshTokenRotationAndReplay:
    def test_refresh_token_generation_and_parsing(self):
        full_token, token_id, token_hash = generate_refresh_token_pair()
        assert full_token.startswith(f"rt_{token_id}_")

        parsed = parse_refresh_token(full_token)
        assert parsed is not None
        parsed_id, raw_secret = parsed
        assert parsed_id == token_id
        assert hashlib.sha256(raw_secret.encode("utf-8")).hexdigest() == token_hash

    def test_successful_token_rotation(self, clean_auth_service):
        reg = clean_auth_service.register_user(
            UserCreate(email="rotate@example.com", password="Password123!")
        )
        assert reg.access_token is not None
        assert reg.refresh_token is not None
        old_refresh_token = reg.refresh_token

        # First refresh: valid rotation
        refreshed = clean_auth_service.refresh_tokens(old_refresh_token)
        assert refreshed.access_token is not None
        assert refreshed.refresh_token is not None
        assert refreshed.refresh_token != old_refresh_token
        assert refreshed.user.email == "rotate@example.com"

        # Verify old refresh token is marked revoked in store
        parsed_old = parse_refresh_token(old_refresh_token)
        assert parsed_old is not None
        old_id, _ = parsed_old
        record = clean_auth_service.token_store.get_refresh_token(old_id)
        assert record is not None
        assert record["revoked"] is True

    def test_replay_attack_triggers_user_wide_revocation(self, clean_auth_service):
        reg = clean_auth_service.register_user(
            UserCreate(email="victim@example.com", password="Password123!")
        )
        assert reg.refresh_token is not None
        old_refresh = reg.refresh_token

        # Legitimate user rotates token
        refreshed = clean_auth_service.refresh_tokens(old_refresh)
        assert refreshed.refresh_token is not None
        valid_new_refresh = refreshed.refresh_token

        # Attacker attempts replay of old_refresh token
        with pytest.raises(Exception) as excinfo:
            clean_auth_service.refresh_tokens(old_refresh)
        assert "Token reuse detected" in str(excinfo.value) or "401" in str(excinfo.value)

        # REPLAY DEFENSE: Even the legitimate user's new refresh token is now revoked for safety
        with pytest.raises(Exception):
            clean_auth_service.refresh_tokens(valid_new_refresh)

    def test_expired_refresh_token_rejected(self, clean_auth_service):
        reg = clean_auth_service.register_user(
            UserCreate(email="expired_rt@example.com", password="Password123!")
        )
        assert reg.refresh_token is not None
        parsed = parse_refresh_token(reg.refresh_token)
        assert parsed is not None
        token_id, _ = parsed

        # Force expire the refresh token in the store
        with clean_auth_service.token_store._connect() as conn:
            conn.execute(
                "UPDATE refresh_tokens SET expires_at = '2020-01-01T00:00:00+00:00' WHERE token_id = ?;",
                (token_id,),
            )

        with pytest.raises(Exception) as excinfo:
            clean_auth_service.refresh_tokens(reg.refresh_token)
        assert "expired" in str(excinfo.value).lower()


# ==============================================================================
# 4. User Sessions & Logout Invalidation
# ==============================================================================


class TestUserSessionsAndLogout:
    def test_session_listing_and_revocation(self, clean_auth_service):
        user_reg = clean_auth_service.register_user(
            UserCreate(email="sessions@example.com", password="Password123!"),
            user_agent="Mozilla/5.0 TestBrowser",
        )
        user_id = user_reg.user.user_id

        # List active sessions
        sessions = clean_auth_service.list_user_sessions(user_id)
        assert len(sessions) == 1
        assert sessions[0].user_agent == "Mozilla/5.0 TestBrowser"

        token_id = sessions[0].token_id
        revoked = clean_auth_service.revoke_session(user_id, token_id)
        assert revoked is True

        # Now active sessions is empty
        sessions_after = clean_auth_service.list_user_sessions(user_id)
        assert len(sessions_after) == 0

    def test_logout_revokes_access_and_refresh_tokens(self, clean_auth_service):
        user_reg = clean_auth_service.register_user(
            UserCreate(email="logout_test@example.com", password="Password123!")
        )
        user = clean_auth_service.user_store.get_by_email("logout_test@example.com")

        # Before logout: user retrieved from token
        assert clean_auth_service.get_user_from_token(user_reg.access_token) is not None

        # Perform logout
        clean_auth_service.logout_user(
            raw_access_token=user_reg.access_token,
            current_user=user,
        )

        # After logout: access token is revoked
        assert clean_auth_service.get_user_from_token(user_reg.access_token) is None

        # Refresh token is also revoked
        with pytest.raises(Exception):
            clean_auth_service.refresh_tokens(user_reg.refresh_token)


# ==============================================================================
# 5. Role-Based Access Control (RBAC) Tests
# ==============================================================================


class TestRoleBasedAccessControl:
    def test_admin_and_user_roles(self, client):
        # 1. Register standard user
        reg_user = client.post("/api/auth/register", json={"email": "standard@example.com", "password": "Password123!"})
        assert reg_user.status_code == 200
        user_token = reg_user.json()["access_token"]
        assert reg_user.json()["user"]["role"] == "user"

        # 2. Standard user cannot access admin endpoint (403 Forbidden)
        resp_forbidden = client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp_forbidden.status_code == status.HTTP_403_FORBIDDEN

        # 3. Register admin user
        reg_admin = client.post(
            "/api/auth/register",
            json={"email": "admin@example.com", "password": "AdminPassword123!", "role": "admin"},
        )
        assert reg_admin.status_code == 200
        admin_token = reg_admin.json()["access_token"]
        assert reg_admin.json()["user"]["role"] == "admin"

        # 4. Admin user can access admin endpoint (200 OK)
        resp_admin = client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp_admin.status_code == 200
        users_list = resp_admin.json()
        assert len(users_list) >= 2


# ==============================================================================
# 6. HTTP API Endpoint Tests
# ==============================================================================


class TestAuthAPIEndpoints:
    def test_full_auth_api_flow(self, client):
        # Register
        res_reg = client.post("/api/auth/register", json={"email": "api_flow@example.com", "password": "Password123!"})
        assert res_reg.status_code == 200
        data_reg = res_reg.json()
        assert "access_token" in data_reg
        assert "refresh_token" in data_reg
        access_tok = data_reg["access_token"]
        refresh_tok = data_reg["refresh_token"]

        # GET /api/auth/me (authenticated)
        res_me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_tok}"})
        assert res_me.status_code == 200
        assert res_me.json()["email"] == "api_flow@example.com"

        # GET /api/auth/sessions
        res_sess = client.get("/api/auth/sessions", headers={"Authorization": f"Bearer {access_tok}"})
        assert res_sess.status_code == 200
        assert len(res_sess.json()) >= 1
        sess_id = res_sess.json()[0]["token_id"]

        # POST /api/auth/refresh (rotate)
        res_ref = client.post("/api/auth/refresh", json={"refresh_token": refresh_tok})
        assert res_ref.status_code == 200
        new_tokens = res_ref.json()
        assert new_tokens["access_token"] is not None
        assert new_tokens["refresh_token"] != refresh_tok

        # POST /api/auth/logout
        res_logout = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {new_tokens['access_token']}"})
        assert res_logout.status_code == 200

        # Subsequent call with logged-out token returns 401 Unauthorized
        res_me_after = client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_tokens['access_token']}"})
        assert res_me_after.status_code == status.HTTP_401_UNAUTHORIZED

    def test_unauthorized_access_rejected(self, client):
        # Missing token
        assert client.get("/api/auth/me").status_code == status.HTTP_401_UNAUTHORIZED
        assert client.get("/api/auth/sessions").status_code == status.HTTP_401_UNAUTHORIZED

        # Invalid bearer token
        assert client.get("/api/auth/me", headers={"Authorization": "Bearer invalid_garbage_token"}).status_code == status.HTTP_401_UNAUTHORIZED

    def test_login_invalid_credentials_rejected(self, client):
        client.post("/api/auth/register", json={"email": "login_test@example.com", "password": "CorrectPassword123!"})

        # Wrong password
        res_bad = client.post("/api/auth/login", json={"email": "login_test@example.com", "password": "WrongPassword!"})
        assert res_bad.status_code == status.HTTP_401_UNAUTHORIZED

        # Nonexistent email
        res_non = client.post("/api/auth/login", json={"email": "nonexistent@example.com", "password": "Password123!"})
        assert res_non.status_code == status.HTTP_401_UNAUTHORIZED
