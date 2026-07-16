"""Ledger rules engine endpoints — CRUD, suggest, teach, match, context-suggest."""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from api.app_state import api_rules_engine, api_context_classifier
from api.deps import get_authenticated_user
from rules_engine import LedgerRule, MatchType

router = APIRouter()


class RuleCreate(BaseModel):
    pattern: str
    target_ledger: str
    match_type: str = "keyword"
    confidence: float = 0.85
    category: str = "expense"


class RuleUpdate(BaseModel):
    pattern: str = ""
    target_ledger: str = ""
    match_type: str = ""
    confidence: float = 0.0
    is_active: bool = True
    category: str = ""


class CorrectionSave(BaseModel):
    description: str
    ledger: str


@router.get("/api/v3/ledger-rules")
async def list_rules(category: str = "", current_user: dict = Depends(get_authenticated_user)):
    rules = api_rules_engine.get_rules(category if category else None)
    return {
        "count": len(rules),
        "rules": [r.to_dict() for r in rules],
    }


@router.post("/api/v3/ledger-rules")
async def create_rule(rule: RuleCreate, current_user: dict = Depends(get_authenticated_user)):
    mt = MatchType(rule.match_type) if rule.match_type else MatchType.KEYWORD
    new_rule = LedgerRule(
        pattern=rule.pattern,
        target_ledger=rule.target_ledger,
        match_type=mt,
        confidence=rule.confidence,
        category=rule.category,
    )
    api_rules_engine.add_rule(new_rule)
    return {"ok": True, "rule": new_rule.to_dict()}


@router.put("/api/v3/ledger-rules")
async def update_rule(old_pattern: str, old_target: str, rule: RuleUpdate, current_user: dict = Depends(get_authenticated_user)):
    mt = MatchType(rule.match_type) if rule.match_type else MatchType.KEYWORD
    new_rule = LedgerRule(
        pattern=rule.pattern or old_pattern,
        target_ledger=rule.target_ledger or old_target,
        match_type=mt,
        confidence=rule.confidence or 0.85,
        is_active=rule.is_active,
        category=rule.category or "expense",
    )
    ok = api_rules_engine.update_rule(old_pattern, old_target, new_rule)
    if not ok:
        raise HTTPException(404, f"Rule '{old_pattern}' \u2192 '{old_target}' not found")
    return {"ok": True, "rule": new_rule.to_dict()}


@router.delete("/api/v3/ledger-rules")
async def delete_rule(pattern: str, target_ledger: str, current_user: dict = Depends(get_authenticated_user)):
    ok = api_rules_engine.remove_rule(pattern, target_ledger)
    if not ok:
        raise HTTPException(404, f"Rule '{pattern}' \u2192 '{target_ledger}' not found")
    return {"ok": True}


@router.post("/api/v3/ledger-rules/suggest")
async def suggest_rules(description: str, current_user: dict = Depends(get_authenticated_user)):
    suggestions = api_rules_engine.suggest_ledgers(description, top_n=5)
    return {
        "description": description,
        "suggestions": suggestions,
        "count": len(suggestions),
    }


@router.post("/api/v3/ledger-rules/teach")
async def teach_rule(body: CorrectionSave, current_user: dict = Depends(get_authenticated_user)):
    rule = LedgerRule(
        pattern=body.description.lower().strip(),
        target_ledger=body.ledger,
        match_type=MatchType.KEYWORD,
        confidence=1.0,
    )
    api_rules_engine.add_rule(rule)
    api_rules_engine.add_correction(body.description, body.ledger)
    return {"ok": True, "rule": rule.to_dict()}


@router.get("/api/v3/ledger-rules/match")
async def match_ledger(description: str, current_user: dict = Depends(get_authenticated_user)):
    result = api_rules_engine.match(description)
    return result.to_dict()


@router.post("/api/v3/ledger/context-suggest")
async def context_suggest(body: dict, current_user: dict = Depends(get_authenticated_user)):
    description = str(body.get("description", "")).strip()
    try:
        amount = float(body.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0.0
    result = api_context_classifier.classify(description, amount=amount)
    return result.to_dict()
