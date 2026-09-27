"""Signed browser-session authorization for local media delivery."""

import hashlib
import os
from typing import Optional
from uuid import uuid4

from fastapi import Request, Response

from app.models import User
from app.services.auth_service import create_jwt_token, decode_jwt_token


MEDIA_ACCESS_COOKIE = "ai_shorts_media_access"
MEDIA_ACCESS_MAX_AGE_SECONDS = 3600
ANONYMOUS_OWNER_PREFIX = "anonymous:"


def _cookie_secure() -> bool:
    return os.environ.get("MEDIA_COOKIE_SECURE", "false").strip().lower() in (
        "true",
        "1",
        "yes",
    )


def _owner_from_cookie(request: Request) -> Optional[str]:
    token = request.cookies.get(MEDIA_ACCESS_COOKIE)
    if not token:
        return None
    payload = decode_jwt_token(token)
    if not payload or payload.get("token_type") != "media_access":
        return None
    owner_id = payload.get("sub")
    return owner_id if isinstance(owner_id, str) and owner_id.strip() else None


def create_media_access_token(owner_id: str) -> str:
    """Create a short-lived signed token scoped to one media owner."""
    return create_jwt_token(
        {"sub": owner_id, "token_type": "media_access"},
        expires_in_seconds=MEDIA_ACCESS_MAX_AGE_SECONDS,
    )


def set_media_access_cookie(response: Response, owner_id: str) -> None:
    """Set a short-lived signed cookie usable by browser media elements."""
    token = create_media_access_token(owner_id)
    response.set_cookie(
        key=MEDIA_ACCESS_COOKIE,
        value=token,
        max_age=MEDIA_ACCESS_MAX_AGE_SECONDS,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/api",
    )


def clear_media_access_cookie(response: Response) -> None:
    response.delete_cookie(MEDIA_ACCESS_COOKIE, path="/api")


def establish_job_owner(
    request: Request,
    response: Response,
    current_user: Optional[User],
) -> str:
    """Return the job owner and refresh its media cookie.

    Authenticated users always win over cookies. Unauthenticated requests may
    reuse only an anonymous owner cookie; a user media cookie is never accepted
    as authentication for job-management APIs.
    """
    if current_user is not None:
        owner_id = current_user.user_id
    else:
        cookie_owner = _owner_from_cookie(request)
        owner_id = (
            cookie_owner
            if cookie_owner and cookie_owner.startswith(ANONYMOUS_OWNER_PREFIX)
            else f"{ANONYMOUS_OWNER_PREFIX}{uuid4()}"
        )
    set_media_access_cookie(response, owner_id)
    return owner_id


def resolve_media_owner(request: Request, current_user: Optional[User]) -> Optional[str]:
    """Resolve ownership for a media request from Bearer auth or signed cookie."""
    if current_user is not None:
        return current_user.user_id
    return _owner_from_cookie(request)


def owner_directory_name(owner_id: str) -> str:
    """Return a filesystem-safe, non-identifying directory name for an owner."""
    return hashlib.sha256(owner_id.encode("utf-8")).hexdigest()[:32]
