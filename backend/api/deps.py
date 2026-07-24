"""Shared FastAPI dependencies for route modules.

In production (AUTH_ENABLED=true / PRODUCTION_MODE / cloud host), validates JWT.
In local development, falls back to the default demo user.
"""

import os
import logging

from fastapi import Header, HTTPException
from config.settings import default_user

logger = logging.getLogger("invosync.deps")


def _resolve_auth_enabled() -> bool:
    """AUTH_ENABLED explicit wins; otherwise auto-enable on known prod hosts."""
    raw = os.getenv("AUTH_ENABLED", "").strip().lower()
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    # Auto-enable when deployed (Render/Railway) or PRODUCTION_MODE is set
    if os.getenv("PRODUCTION_MODE", "").lower() in ("true", "1", "yes"):
        return True
    if os.getenv("RENDER") or os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("FLY_APP_NAME"):
        return True
    return False


_AUTH_ENABLED = _resolve_auth_enabled()


def _jwt_secret() -> str:
    """Use the same secret as auth.py (including ephemeral generated secret).

    Critical: deps must NOT read os.getenv('JWT_SECRET') alone — auth.py may
    generate an ephemeral secret when the env var is empty, and a mismatch
    makes every authenticated request fail with 401 after login.
    """
    try:
        from auth import JWT_SECRET
        if JWT_SECRET:
            return JWT_SECRET
    except Exception as e:
        logger.warning("Could not import auth.JWT_SECRET: %s", e)
    secret = os.getenv("JWT_SECRET", "")
    if not secret:
        raise HTTPException(500, "JWT_SECRET not configured")
    return secret


def decode_jwt(token: str) -> dict:
    """Decode access JWT with the same secret used to issue tokens."""
    try:
        import jwt as pyjwt
        secret = _jwt_secret()
        payload = pyjwt.decode(token, secret, algorithms=["HS256"])
        # Reject refresh tokens used as access tokens
        if payload.get("type") == "refresh":
            raise HTTPException(401, "Refresh token cannot be used as access token")
        return payload
    except ImportError:
        raise HTTPException(500, "JWT library not available")
    except HTTPException:
        raise
    except Exception as e:
        # pyjwt.ExpiredSignatureError / InvalidTokenError
        msg = str(e).lower()
        if "expired" in msg:
            raise HTTPException(401, "Token expired")
        raise HTTPException(401, "Invalid token")


async def get_authenticated_user(authorization: str = Header(None)) -> dict:
    """Validate JWT from Authorization header, enrich from DB if available.

    When AUTH_ENABLED=false (local dev), returns the default demo user.
    """
    if not _AUTH_ENABLED:
        return await default_user()

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid authorization header")
    token = authorization.split(" ", 1)[1]
    jwt_data = decode_jwt(token)

    try:
        import database as db
        if db.users is not None:
            user = await db.find_user(jwt_data.get("email", ""))
            if user:
                for key, val in user.items():
                    if key not in ("_id", "password_hash"):
                        jwt_data[key] = val
                # Stable id field for downstream code
                if "user_id" not in jwt_data and user.get("_id") is not None:
                    jwt_data["user_id"] = str(user["_id"])
    except Exception:
        logger.warning("Failed to enrich user from DB, using token claims only")

    return jwt_data
