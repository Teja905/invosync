"""Banking rules and statement processing endpoints."""

from fastapi import APIRouter, HTTPException, Depends

import database as db
from api.deps import get_authenticated_user
from config.settings import user_config_from_current

router = APIRouter()


@router.get("/api/v3/banking/rules")
async def banking_rules_list(current_user: dict = Depends(get_authenticated_user)):
    """List all banking auto-categorization rules for the user."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    rules = await db.list_banking_rules(user_id)
    return [{"id": str(r["_id"]), "keyword": r["keyword"], "voucher_type": r["voucher_type"], "target_ledger": r["target_ledger"]} for r in rules]


@router.post("/api/v3/banking/rules")
async def banking_rules_create(body: dict, current_user: dict = Depends(get_authenticated_user)):
    """Create a new keyword-based banking categorization rule."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    keyword = (body or {}).get("keyword", "").strip()
    if not keyword:
        raise HTTPException(400, "keyword is required")
    doc = await db.create_banking_rule(
        user_id=user_id,
        keyword=keyword,
        voucher_type=body.get("voucher_type", "Receipt"),
        target_ledger=body.get("target_ledger", "Suspense"),
    )
    return {"status": "ok", "rule": {"id": str(doc.get("_id", "")), "keyword": keyword}}


@router.delete("/api/v3/banking/rules/{rule_id}")
async def banking_rules_delete(rule_id: str, current_user: dict = Depends(get_authenticated_user)):
    """Delete a banking rule by its ID."""
    user_id = current_user.get("user_id", current_user.get("email", ""))
    await db.delete_banking_rule(rule_id, user_id)
    return {"status": "ok"}


@router.post("/api/v3/banking/process")
async def banking_process_statement(body: dict, current_user: dict = Depends(get_authenticated_user)):
    """Apply banking rules to transactions and generate Tally bank XML."""
    from ledger_mapping import apply_banking_rules_to_transactions
    from xml_generator import generate_tally_bank_xml
    user_id = current_user.get("user_id", current_user.get("email", ""))
    transactions = (body or {}).get("transactions", [])
    bank_ledger = (body or {}).get("bank_ledger", "Bank")
    if not transactions:
        raise HTTPException(400, "transactions list is required")
    user_cfg = user_config_from_current(current_user)
    active_company = user_cfg.get("active_company", "")
    rules = await db.list_banking_rules(user_id)
    processed = apply_banking_rules_to_transactions(transactions, rules)
    xml = generate_tally_bank_xml(processed, bank_ledger_name=bank_ledger, company_name=active_company)
    return {
        "total": len(processed),
        "processed": processed,
        "xml": xml,
    }
