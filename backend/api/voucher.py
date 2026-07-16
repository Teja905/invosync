"""Voucher type suggestion endpoint."""

from fastapi import APIRouter, Depends

from api.app_state import company_config
from api.deps import get_authenticated_user
from config.settings import user_config_from_current
from schemas import VoucherType
from voucher_classifier import classify_voucher_type, classify_service_vs_goods

router = APIRouter()


@router.post("/api/v3/voucher-type/suggest")
async def suggest_voucher_type(data: dict, current_user: dict = Depends(get_authenticated_user)):
    user_cfg = user_config_from_current(current_user)
    state_code = user_cfg.get("company_state_code") or company_config.state_code
    vtype, rationale = classify_voucher_type(data, state_code)
    return {
        "suggested": vtype.value,
        "rationale": rationale,
        "user_can_override": True,
        "available_types": [t.value for t in VoucherType],
        "is_service": classify_service_vs_goods(data.get("line_items", [])),
    }
