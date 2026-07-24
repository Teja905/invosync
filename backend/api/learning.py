"""Learning engine endpoints — stats, teach, corrections, vendor ledger mappings."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import database as db
from api.app_state import learner, api_rules_engine
from api.deps import get_authenticated_user
from api.corrections import CorrectionSave
from rules_engine import LedgerRule, MatchType

router = APIRouter()


@router.get("/api/v3/learning/stats")
async def learning_stats(current_user: dict = Depends(get_authenticated_user)):
    email = current_user.get("email", "")
    stats = learner.stats()
    memory = await db.get_correction_memory(email)
    stats["corrections_count"] = len(memory)
    vendor_map = await db.get_all_vendor_ledger_mappings(email)
    stats["vendor_mappings_count"] = len(vendor_map)
    return stats


@router.post("/api/v3/learning/teach")
async def learn_from_correction(body: CorrectionSave, current_user: dict = Depends(get_authenticated_user)):
    email = current_user.get("email", "")
    await learner.learn(body.description, body.ledger, email=email)
    rule = LedgerRule(
        pattern=body.description.lower().strip(),
        target_ledger=body.ledger,
        match_type=MatchType.KEYWORD,
        confidence=1.0,
    )
    api_rules_engine.add_rule(rule)
    return {"ok": True, "rule": rule.to_dict()}


@router.get("/api/v3/learning/corrections")
async def learning_corrections(current_user: dict = Depends(get_authenticated_user)):
    email = current_user.get("email", "")
    memory = await db.get_correction_memory(email)
    return {"corrections": memory, "count": len(memory)}


# ---- Vendor Ledger Mappings (auto-learn) ----

class VendorLedgerMapping(BaseModel):
    vendor_name: str
    ledger_name: str
    gstin: str = ""


@router.get("/api/v3/learning/vendor-map")
async def list_vendor_ledger_mappings(current_user: dict = Depends(get_authenticated_user)):
    """Return all saved vendor→ledger mappings."""
    email = current_user.get("email", "")
    mappings = await db.get_all_vendor_ledger_mappings(email)
    return {"mappings": mappings, "count": len(mappings)}


@router.get("/api/v3/learning/vendor-map/{vendor_name:path}")
async def lookup_vendor_ledger(vendor_name: str, current_user: dict = Depends(get_authenticated_user)):
    """Look up saved ledger for a specific vendor (normalized match)."""
    email = current_user.get("email", "")
    ledger = await db.get_vendor_ledger_mapping(email, vendor_name)
    if ledger:
        return {"vendor_name": vendor_name, "ledger_name": ledger, "found": True, "match_type": "normalized"}
    return {"vendor_name": vendor_name, "ledger_name": None, "found": False}


@router.get("/api/v3/learning/vendor-map-by-gstin/{gstin}")
async def lookup_vendor_ledger_by_gstin(gstin: str, current_user: dict = Depends(get_authenticated_user)):
    """Look up saved ledger by GSTIN (most reliable match)."""
    email = current_user.get("email", "")
    ledger = await db.get_vendor_ledger_by_gstin(email, gstin)
    if ledger:
        return {"gstin": gstin, "ledger_name": ledger, "found": True}
    return {"gstin": gstin, "ledger_name": None, "found": False}


@router.post("/api/v3/learning/vendor-map")
async def save_vendor_ledger(body: VendorLedgerMapping, current_user: dict = Depends(get_authenticated_user)):
    """Save a vendor→ledger mapping (called when user selects a ledger)."""
    email = current_user.get("email", "")
    if not body.vendor_name.strip() or not body.ledger_name.strip():
        raise HTTPException(400, "vendor_name and ledger_name are required")
    await db.save_vendor_ledger_mapping(email, body.vendor_name, body.ledger_name, body.gstin)
    return {"ok": True, "vendor_name": body.vendor_name, "ledger_name": body.ledger_name}


@router.delete("/api/v3/learning/vendor-map/{vendor_name:path}")
async def delete_vendor_ledger(vendor_name: str, current_user: dict = Depends(get_authenticated_user)):
    """Remove a vendor→ledger mapping."""
    email = current_user.get("email", "")
    await db.delete_vendor_ledger_mapping(email, vendor_name)
    return {"ok": True}
