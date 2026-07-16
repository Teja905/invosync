"""Correction memory endpoints — learn, forget, list, clear."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import database as db
from api.app_state import learner
from api.deps import get_authenticated_user
from audit_log import audit as audit_logger

router = APIRouter()


class CorrectionSave(BaseModel):
    description: str
    ledger: str


@router.get("/corrections")
async def list_corrections(current_user: dict = Depends(get_authenticated_user)):
    """Return all stored ledger correction mappings for the user."""
    email = current_user.get("email", "")
    memory = learner.get_corrections()
    if not memory:
        memory = await db.get_correction_memory(email)
    return {"corrections": memory, "count": len(memory)}


@router.post("/corrections")
async def save_correction(body: CorrectionSave, current_user: dict = Depends(get_authenticated_user)):
    """Save a description-to-ledger correction for future extraction learning."""
    email = current_user.get("email", "")
    await learner.learn(body.description, body.ledger, email=email)
    await audit_logger.log_correction(email, body.description, body.ledger, "manual")
    return {"ok": True, "saved": f"{body.description.lower().strip()} \u2192 {body.ledger}"}


@router.post("/corrections/forget")
async def forget_correction(body: CorrectionSave, current_user: dict = Depends(get_authenticated_user)):
    """Remove a single correction mapping from the user's learning memory."""
    email = current_user.get("email", "")
    await learner.forget(body.description, email=email)
    await audit_logger.log_correction(email, body.description, "", "forgot")
    return {"ok": True, "forgotten": body.description}


@router.delete("/corrections")
async def clear_corrections(current_user: dict = Depends(get_authenticated_user)):
    """Delete all correction mappings and reset the in-memory learner."""
    email = current_user.get("email", "")
    await db.users.update_one({"email": email.lower().strip()}, {"$set": {"correction_memory": {}}})
    learner._corrections.clear()
    return {"ok": True, "cleared": True}


@router.get("/corrections/stats")
async def correction_stats(current_user: dict = Depends(get_authenticated_user)):
    """Returns learning statistics for the frontend dashboard."""
    return learner.stats()
