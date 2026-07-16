"""User configuration endpoints."""

from fastapi import APIRouter, Depends

import database as db
from api.app_state import company_config
from api.deps import get_authenticated_user
from audit_log import audit as audit_logger
from config.settings import COMPANY_CONFIG_FIELDS, config_overrides, user_config_from_current
from core.logging import get_logger
from crypto_utils import encrypt

router = APIRouter()
logger = get_logger(__name__)


@router.get("/api/v3/config")
async def get_config(current_user: dict = Depends(get_authenticated_user)):
    """Return the current user's company configuration."""
    user_cfg = user_config_from_current(current_user)
    if user_cfg:
        return user_cfg
    return company_config.to_env_config()


@router.post("/api/v3/config")
async def save_config(data: dict, current_user: dict = Depends(get_authenticated_user)):
    """Save user-submitted company configuration fields with audit logging."""
    user_id = current_user.get("user_id", "default")
    allowed = set(COMPANY_CONFIG_FIELDS)
    clean = {k: v for k, v in data.items() if k in allowed and v}
    if clean:
        old_config = config_overrides.get(user_id, {})
        if user_id not in config_overrides:
            config_overrides[user_id] = {}

        encrypted_fields = {"tally_password"}
        db_clean = {}
        for key, value in clean.items():
            if key in encrypted_fields and value:
                db_clean[key] = encrypt(value)
                clean[key] = value
            else:
                db_clean[key] = value

        config_overrides[user_id].update(clean)
        for key, value in clean.items():
            old_value = old_config.get(key, "")
            if old_value != value:
                await audit_logger.log_config_change(user_id, key, str(old_value), str(value))
        if db.users is not None:
            try:
                await db.users.update_one(
                    {"email": current_user.get("email", "").lower()},
                    {"$set": clean},
                    upsert=True,
                )
            except Exception as e:
                logger.warning("Config persist failed: %s", e)
    return {**current_user, **config_overrides.get(user_id, {})}
