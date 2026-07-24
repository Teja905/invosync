"""JWT helpers — single source of truth is backend/auth.py.

This module previously used a separate JWT_SECRET_KEY + hardcoded admin123 path,
which split secrets from the real multi-user auth system. All callers should
import from `auth` (backend/auth.py). This file re-exports for backward compat.
"""

from __future__ import annotations

import os
from typing import Optional

from core.logging import get_logger

logger = get_logger(__name__)

# Re-export from the real auth module so secrets never diverge
try:
    from auth import (
        JWT_SECRET as SECRET_KEY,
        create_jwt,
        create_refresh_token,
        decode_jwt,
        JWT_EXPIRY_HOURS,
        REFRESH_EXPIRY_DAYS,
    )
except Exception:
    # Fallback only during very early import / tests without full app
    import secrets as _secrets
    SECRET_KEY = os.getenv("JWT_SECRET") or _secrets.token_urlsafe(64)
    create_jwt = None  # type: ignore
    create_refresh_token = None  # type: ignore
    decode_jwt = None  # type: ignore
    JWT_EXPIRY_HOURS = 24
    REFRESH_EXPIRY_DAYS = 30

# Refresh uses same secret as access (type claim distinguishes them)
REFRESH_SECRET_KEY = SECRET_KEY
ACCESS_TOKEN_EXPIRE_MINUTES = JWT_EXPIRY_HOURS * 60
REFRESH_TOKEN_EXPIRE_DAYS = REFRESH_EXPIRY_DAYS

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@invosync.com")


def verify_password(plain: str) -> bool:
    """Legacy single-admin check — prefer multi-user auth.py login."""
    import hashlib
    pw = os.getenv("ADMIN_PASSWORD", "")
    if not pw:
        logger.warning("ADMIN_PASSWORD not set — legacy verify_password always fails")
        return False
    return hashlib.sha256(plain.encode()).hexdigest() == hashlib.sha256(pw.encode()).hexdigest()


def create_tokens(email: str) -> dict:
    """Create access + refresh pair using the unified auth secret."""
    if create_jwt is None or create_refresh_token is None:
        raise RuntimeError("auth module not available")
    user_id = email  # legacy path has no DB id
    return {
        "token": create_jwt(email, user_id),
        "refresh_token": create_refresh_token(email, user_id),
        "email": email,
    }


def verify_access_token(token: str) -> Optional[str]:
    """Return email if access token is valid."""
    if decode_jwt is None:
        return None
    try:
        payload = decode_jwt(token)
        if payload.get("type") == "refresh":
            return None
        return payload.get("email")
    except Exception:
        return None


def verify_refresh_token(token: str) -> Optional[str]:
    """Return email if refresh token is valid."""
    if decode_jwt is None:
        return None
    try:
        payload = decode_jwt(token)
        if payload.get("type") != "refresh":
            return None
        return payload.get("email")
    except Exception:
        return None
