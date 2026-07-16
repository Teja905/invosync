"""Client CRUD endpoints."""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

import database as db
from api.deps import get_authenticated_user

router = APIRouter()


class ClientCreate(BaseModel):
    company_name: str
    client_name: str
    gstin: str = ""


class ClientUpdate(BaseModel):
    company_name: str = ""
    client_name: str = ""
    gstin: str = ""


@router.post("/clients")
async def create_client(data: ClientCreate, current_user: dict = Depends(get_authenticated_user)):
    """Create a new client record for the authenticated user."""
    if db.clients is None:
        raise HTTPException(503, "Database not available")
    client = await db.create_client(
        user_id=current_user.get("user_id", current_user.get("email", "")),
        company_name=data.company_name,
        client_name=data.client_name,
        gstin=data.gstin,
    )
    return {
        "client_id": client["client_id"],
        "company_name": client["company_name"],
        "client_name": client["client_name"],
        "gstin": client["gstin"],
        "created_at": client["created_at"],
    }


@router.get("/clients")
async def list_clients(current_user: dict = Depends(get_authenticated_user)):
    """List all clients belonging to the authenticated user."""
    if db.clients is None:
        return []
    user_id = current_user.get("user_id", current_user.get("email", ""))
    records = await db.list_clients(user_id)
    return [
        {
            "client_id": c["client_id"],
            "company_name": c["company_name"],
            "client_name": c["client_name"],
            "gstin": c.get("gstin", ""),
            "created_at": c["created_at"],
            "invoice_count": c.get("invoice_count", 0),
        }
        for c in records
    ]


@router.get("/clients/{client_id}")
async def get_client(client_id: int, current_user: dict = Depends(get_authenticated_user)):
    """Retrieve a single client by ID with ownership check."""
    if db.clients is None:
        raise HTTPException(503, "Database not available")
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if client.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")
    return {
        "client_id": client["client_id"],
        "company_name": client["company_name"],
        "client_name": client["client_name"],
        "gstin": client.get("gstin", ""),
        "created_at": client["created_at"],
        "invoice_count": client.get("invoice_count", 0),
    }


@router.put("/clients/{client_id}")
async def update_client(client_id: int, data: ClientUpdate, current_user: dict = Depends(get_authenticated_user)):
    """Update an existing client's company name, client name, or GSTIN."""
    if db.clients is None:
        raise HTTPException(503, "Database not available")
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if client.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")
    await db.update_client(client_id, data.model_dump(exclude_unset=True))
    return {"ok": True}


@router.delete("/clients/{client_id}")
async def delete_client(client_id: int, current_user: dict = Depends(get_authenticated_user)):
    """Delete a client record after verifying ownership."""
    if db.clients is None:
        raise HTTPException(503, "Database not available")
    client = await db.get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")
    user_id = current_user.get("user_id", current_user.get("email", ""))
    if client.get("user_id") != user_id:
        raise HTTPException(403, "Access denied")
    await db.delete_client(client_id)
    return {"ok": True}
