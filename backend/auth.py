"""Email/password JWT authentication module for CA firms."""

import os
import hashlib
import secrets
import logging
from typing import Optional
import jwt
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel

import database as db
from audit_log import audit as audit_logger

logger = logging.getLogger("invosync.auth")

JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGO = "HS256"
JWT_EXPIRY_HOURS = 72

if not JWT_SECRET:
    JWT_SECRET = secrets.token_urlsafe(64)
    logger.warning("JWT_SECRET not set — generated ephemeral secret. Set JWT_SECRET env var for production.")
elif JWT_SECRET in ("dev-secret-change-in-production", "change-this-to-a-long-random-secret-in-production", "secret", "changeme"):
    logger.warning("JWT_SECRET is using a known default value. Set a strong random secret in production.")

ADMIN_EMAILS = set(
    e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()
)

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupRequest(BaseModel):
    email: str
    password: str
    name: str


class LoginRequest(BaseModel):
    email: str
    password: str


class ProfileUpdate(BaseModel):
    name: str = ""
    company_name: str = ""
    company_gstin: str = ""
    company_state_code: str = ""
    correction_memory: Optional[dict] = None
    purchase_ledger: str = ""
    sales_ledger: str = ""
    bank_ledger: str = ""
    tds_ledger: str = ""
    round_off_ledger: str = ""
    freight_ledger: str = ""
    suspense_ledger: str = ""
    sundry_creditors_group: str = ""
    sundry_debtors_group: str = ""
    purchase_accounts_group: str = ""
    sales_accounts_group: str = ""
    bank_accounts_group: str = ""
    current_liabilities_group: str = ""
    duties_taxes_group: str = ""


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return f"{salt}${pwd_hash.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, pwd_hash = stored.split("$", 1)
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
        return check.hex() == pwd_hash
    except (ValueError, AttributeError):
        return False


def create_jwt(email: str, user_id: str) -> str:
    payload = {
        "email": email,
        "user_id": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def decode_jwt(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")


async def get_current_user(authorization: str = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid authorization header")
    token = authorization.split(" ", 1)[1]
    jwt_data = decode_jwt(token)
    # Enrich with stored user data (company config etc.) when DB is available
    if db.users is not None:
        try:
            user = await db.find_user(jwt_data.get("email", ""))
            if user:
                for key, val in user.items():
                    if key not in ("_id", "password_hash"):
                        jwt_data[key] = val
        except Exception:
            pass
    return jwt_data


async def get_admin_user(current_user: dict = Depends(get_current_user)) -> dict:
    email = current_user.get("email", "").lower()
    if email not in ADMIN_EMAILS:
        raise HTTPException(403, "Admin access required")
    return current_user


_COMPANY_FIELDS = [
    "company_name", "company_gstin", "company_state_code",
    "purchase_ledger", "sales_ledger", "bank_ledger",
    "tds_ledger", "round_off_ledger", "freight_ledger", "suspense_ledger",
    "sundry_creditors_group", "sundry_debtors_group",
    "purchase_accounts_group", "sales_accounts_group",
    "bank_accounts_group", "current_liabilities_group",
    "duties_taxes_group",
]


@router.post("/signup")
async def signup(req: SignupRequest):
    email = req.email.lower().strip()
    if not email or not req.password or not req.name:
        raise HTTPException(400, "Email, password, and name are required")
    if len(req.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if not any(c.isupper() for c in req.password):
        raise HTTPException(400, "Password must contain at least one uppercase letter")
    if not any(c.isdigit() for c in req.password):
        raise HTTPException(400, "Password must contain at least one number")
    if db.users is None:
        raise HTTPException(503, "Database not available")

    existing = await db.find_user(email)
    if existing:
        raise HTTPException(409, "An account with this email already exists")

    pwd_hash = _hash_password(req.password)
    user = await db.create_user(email, pwd_hash, req.name)
    token = create_jwt(email, str(user["_id"]))
    await audit_logger.log_auth("signup", email, True, details=f"name={req.name}")

    user_obj = {
        "email": email,
        "name": req.name.strip(),
        "role": "admin" if email in ADMIN_EMAILS else "user",
    }
    for f in _COMPANY_FIELDS:
        user_obj[f] = ""
    return {
        "token": token,
        "user": user_obj,
    }


@router.post("/login")
async def login(req: LoginRequest):
    email = req.email.lower().strip()
    if db.users is None:
        raise HTTPException(503, "Database not available")

    user = await db.find_user(email)
    if not user:
        raise HTTPException(401, "Invalid email or password")

    if not _verify_password(req.password, user.get("password_hash", "")):
        await audit_logger.log_auth("login", email, False, details="invalid_password")
        raise HTTPException(401, "Invalid email or password")

    await db.update_user_login(email)
    token = create_jwt(email, str(user["_id"]))
    await audit_logger.log_auth("login", email, True, details=f"user_id={user['_id']}")

    user_obj = {
        "email": email,
        "name": user.get("name", ""),
        "role": user.get("role", "user"),
    }
    for f in _COMPANY_FIELDS:
        user_obj[f] = user.get(f, "")
    return {
        "token": token,
        "user": user_obj,
    }


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    if db.users is None:
        raise HTTPException(503, "Database not available")
    user = await db.find_user(current_user["email"])
    if not user:
        raise HTTPException(404, "User not found")
    result = {
        "email": user.get("email", ""),
        "name": user.get("name", ""),
        "role": user.get("role", "user"),
        "created_at": user.get("created_at", ""),
        "last_login": user.get("last_login", ""),
        "invoice_count": user.get("invoice_count", 0),
    }
    for field in _COMPANY_FIELDS:
        result[field] = user.get(field, "")
    return result


@router.post("/profile")
async def update_profile(
    profile: ProfileUpdate,
    current_user: dict = Depends(get_current_user),
):
    if db.users is not None:
        set_fields = {}
        if profile.name.strip():
            set_fields["name"] = profile.name.strip()
        for field in _COMPANY_FIELDS:
            val = getattr(profile, field, "")
            if val:
                set_fields[field] = val.strip()
        if set_fields:
            await db.users.update_one(
                {"email": current_user["email"]},
                {"$set": set_fields},
            )
    return {"ok": True, "message": "Profile updated"}


@router.post("/company-config")
async def save_company_config(
    profile: ProfileUpdate,
    current_user: dict = Depends(get_current_user),
):
    return await update_profile(profile, current_user)


@router.get("/admin/users")
async def list_users(admin_user: dict = Depends(get_admin_user)):
    if db.users is None:
        return []
    cursor = db.users.find({}, sort=[("created_at", -1)])
    users_list = await cursor.to_list(length=1000)
    result = []
    for u in users_list:
        result.append({
            "email": u.get("email", ""),
            "name": u.get("name", ""),
            "role": u.get("role", "user"),
            "created_at": u.get("created_at", ""),
            "last_login": u.get("last_login", ""),
            "invoice_count": u.get("invoice_count", 0),
        })
    return result
