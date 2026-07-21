"""Shared FastAPI dependencies for route modules.

In production (AUTH_ENABLED=true), validates JWT on every request.
In development, falls back to the default demo user.
"""

import os
import logging

from fastapi import Header, HTTPException
from config.settings import default_user

logger = logging.getLogger("invosync.deps")

_AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() in ("true", "1", "yes")


def decode_jwt(token: str) -> dict:
    """Minimal JWT decode without circular import of auth.py JWT_SECRET."""
    try:
        import jwt as pyjwt
        secret = os.getenv("JWT_SECRET", "")
        if not secret:
            raise HTTPException(500, "JWT_SECRET not configured")
        return pyjwt.decode(token, secret, algorithms=["HS256"])
    except ImportError:
        raise HTTPException(500, "JWT library not available")
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")


async def get_authenticated_user(authorization: str = Header(None)) -> dict:
    """Validate JWT from Authorization header, enrich from DB if available.

    When AUTH_ENABLED=false (dev mode), returns the default demo user.
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
    except Exception:
        logger.warning("Failed to enrich user from DB, using token claims only")

    return jwt_data

