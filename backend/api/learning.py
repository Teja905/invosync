"""Learning engine endpoints — stats, teach, corrections."""

from fastapi import APIRouter, Depends

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
