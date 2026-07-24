"""Auth endpoints — login and token refresh.

Response shape preserved for backward compat with the C# connector:
  ``{ "token": "...", "refresh_token": "...", "email": "..." }``
"""

from fastapi import APIRouter, HTTPException, Request

from core.auth import (
    create_tokens, verify_password, verify_access_token, verify_refresh_token,
    ADMIN_EMAIL,
)
from core.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.post("/api/auth/login")
async def login(body: dict):
    """Authenticate with email and password, returning access and refresh tokens."""
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""

    if not email or not password:
        raise HTTPException(400, "Email and password are required")

    if email != ADMIN_EMAIL or not verify_password(password):
        raise HTTPException(401, "Invalid email or password")

    tokens = create_tokens(email)
    logger.info("Login: %s", email)
    return tokens


@router.post("/api/auth/refresh")
async def refresh(request: Request):
    """Exchange a valid refresh token for a new token pair."""
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    refresh_token = body.get("refresh_token") or ""

    email = verify_refresh_token(refresh_token)
    if not email:
        raise HTTPException(401, "Invalid or expired refresh token")

    tokens = create_tokens(email)
    logger.info("Token refresh: %s", email)
    return tokens


@router.get("/api/auth/me")
async def me(request: Request):
    """Return the current authenticated user's profile from their access token."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid Authorization header")

    token = auth_header.removeprefix("Bearer ")
    email = verify_access_token(token)
    if not email:
        raise HTTPException(401, "Invalid or expired access token")

    return {"email": email, "name": email.split("@")[0], "role": "admin"}
