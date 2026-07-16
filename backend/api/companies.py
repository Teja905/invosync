"""Multi-company CRUD endpoints."""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

import database as db
from api.deps import get_authenticated_user

router = APIRouter()


class CompanyCreate(BaseModel):
    company_name: str
    company_gstin: str = ""
    state_code: str = ""
    purchase_ledger: str = "Purchase"
    sales_ledger: str = "Sales"
    bank_ledger: str = "Bank"


class CompanyUpdate(BaseModel):
    company_name: str = ""
    company_gstin: str = ""
    state_code: str = ""
    purchase_ledger: str = ""
    sales_ledger: str = ""
    bank_ledger: str = ""
    active: bool = True


@router.get("/api/v3/companies")
async def list_companies(current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    comps = await db.list_companies(user_id)
    result = []
    for c in comps:
        result.append({
            "company_id": c["company_id"],
            "company_name": c.get("company_name", ""),
            "company_gstin": c.get("company_gstin", ""),
            "state_code": c.get("state_code", ""),
            "purchase_ledger": c.get("purchase_ledger", "Purchase"),
            "sales_ledger": c.get("sales_ledger", "Sales"),
            "bank_ledger": c.get("bank_ledger", "Bank"),
            "created_at": c.get("created_at", ""),
        })
    return {"companies": result, "count": len(result)}


@router.post("/api/v3/companies")
async def create_company(body: CompanyCreate, current_user: dict = Depends(get_authenticated_user)):
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if not body.company_name:
        raise HTTPException(400, "company_name is required")
    doc = await db.create_company(
        user_id=user_id,
        name=body.company_name,
        gstin=body.company_gstin,
        state_code=body.state_code,
        purchase_ledger=body.purchase_ledger,
        sales_ledger=body.sales_ledger,
        bank_ledger=body.bank_ledger,
    )
    return {"company_id": doc["company_id"], "company_name": doc["company_name"]}


@router.put("/api/v3/companies/{company_id}")
async def update_company(company_id: int, body: CompanyUpdate, current_user: dict = Depends(get_authenticated_user)):
    existing = await db.get_company(company_id)
    if not existing:
        raise HTTPException(404, "Company not found")
    updates = {k: v for k, v in body.model_dump().items() if v}
    await db.update_company(company_id, updates)
    return {"ok": True, "company_id": company_id}


@router.delete("/api/v3/companies/{company_id}")
async def delete_company(company_id: int, current_user: dict = Depends(get_authenticated_user)):
    existing = await db.get_company(company_id)
    if not existing:
        raise HTTPException(404, "Company not found")
    await db.delete_company(company_id)
    return {"ok": True, "deleted": company_id}


@router.post("/api/v3/companies/{company_id}/switch")
async def switch_company(company_id: int, current_user: dict = Depends(get_authenticated_user)):
    existing = await db.get_company(company_id)
    if not existing:
        raise HTTPException(404, "Company not found")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if db.organizations is not None:
        await db.execute_db_write_with_retry(
            db.organizations.update_one,
            {"org_id": user_id},
            {"$set": {"active_company_id": company_id, "active_company": existing.get("company_name", "")}},
            upsert=True,
        )
    return {
        "ok": True,
        "company_id": company_id,
        "company_name": existing.get("company_name", ""),
        "company_gstin": existing.get("company_gstin", ""),
        "state_code": existing.get("state_code", ""),
    }


@router.get("/api/v3/companies/{company_id}/analytics")
async def company_analytics(company_id: int, current_user: dict = Depends(get_authenticated_user)):
    existing = await db.get_company(company_id)
    if not existing:
        raise HTTPException(404, "Company not found")
    analytics = await db.get_company_analytics(company_id)
    return {"ok": True, "company_id": company_id, "analytics": analytics}
