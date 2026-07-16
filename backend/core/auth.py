"""JWT authentication — token creation, verification, refresh.

Kept simple: no user database, uses a single admin credential from env vars.
"""

import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

from core.logging import get_logger

logger = get_logger(__name__)

# Env‑based config
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-change-in-production")
REFRESH_SECRET_KEY = os.getenv("JWT_REFRESH_SECRET", "dev-refresh-secret-change-in-production")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("JWT_REFRESH_EXPIRE_DAYS", "7"))

# Single admin credential (set in production env)
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@invosync.com")
_ADMIN_PASSWORD_HASH = None


def _get_admin_password_hash() -> str:
    global _ADMIN_PASSWORD_HASH
    if _ADMIN_PASSWORD_HASH is None:
        pw = os.getenv("ADMIN_PASSWORD", "admin123")
        _ADMIN_PASSWORD_HASH = hashlib.sha256(pw.encode()).hexdigest()
    return _ADMIN_PASSWORD_HASH


def verify_password(plain: str) -> bool:
    return hashlib.sha256(plain.encode()).hexdigest() == _get_admin_password_hash()


def create_tokens(email: str) -> dict:
    now = datetime.now(timezone.utc)
    access_token = jwt.encode(
        {
            "sub": email,
            "iat": now,
            "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        },
        SECRET_KEY,
        algorithm="HS256",
    )
    refresh_token = jwt.encode(
        {
            "sub": email,
            "iat": now,
            "exp": now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        },
        REFRESH_SECRET_KEY,
        algorithm="HS256",
    )
    return {"token": access_token, "refresh_token": refresh_token, "email": email}


def verify_access_token(token: str) -> Optional[str]:
    """Return the email (subject) if valid, ``None`` otherwise."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload.get("sub")
    except jwt.ExpiredSignatureError:
        logger.debug("Access token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.debug("Invalid access token: %s", e)
        return None


def verify_refresh_token(token: str) -> Optional[str]:
    """Return the email if the refresh token is valid, ``None`` otherwise."""
    try:
        payload = jwt.decode(token, REFRESH_SECRET_KEY, algorithms=["HS256"])
        return payload.get("sub")
    except jwt.ExpiredSignatureError:
        logger.debug("Refresh token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.debug("Invalid refresh token: %s", e)
        return None
