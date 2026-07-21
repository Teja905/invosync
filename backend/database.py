"""MongoDB async database layer — production-grade with pagination, retry, and correct field paths."""

import asyncio
import difflib
import re
from typing import Optional
import hashlib
import logging
import os
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import AutoReconnect, ConnectionFailure
from bson.objectid import ObjectId

from crypto_utils import encrypt, decrypt


def calculate_file_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


logger = logging.getLogger("invosync.database")


async def execute_db_write_with_retry(async_func, *args, max_retries: int = 3, **kwargs):
    delay = 0.5
    for attempt in range(1, max_retries + 1):
        try:
            return await async_func(*args, **kwargs)
        except (AutoReconnect, ConnectionFailure) as db_err:
            if attempt == max_retries:
                logger.critical("Database write failed after %d attempts: %s", max_retries, db_err)
                raise
            logger.warning("Transient DB error (attempt %d/%d), retrying in %.1fs: %s",
                           attempt, max_retries, delay, db_err)
            await asyncio.sleep(delay)
            delay *= 2


_client = None
_db = None
invoices = None
counters = None
users = None
clients = None
banking_rules = None
organizations = None
companies = None
audit_logs = None
journal_lines = None
ledger_types = None
subscriptions = None
plans = None
client_users = None
ai_cache = None

# Sentinel value to detect uninitialized collections
_NOT_INITIALIZED = "database not connected — call connect() first"


def require_connected():
    """Guard: raise a clear error if a collection is accessed before connect().

    Call this at the top of any function that accesses a collection variable.
    Catches the common bug where a module imports `db.invoices` but `connect()`
    hasn't been called yet, giving a confusing `AttributeError: 'NoneType'...`.
    """
    if invoices is None:
        raise RuntimeError(
            "Database not connected. "
            "Ensure `await db.connect()` is called (in lifespan) before using collections."
        )


async def connect():
    global _client, _db, invoices, counters, users, clients, banking_rules, organizations, companies, audit_logs, journal_lines, ledger_types, subscriptions, plans, client_users, ai_cache
    uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    # Bounded connection pool so 1000+ concurrent users don't exhaust sockets.
    _client = AsyncIOMotorClient(
        uri,
        serverSelectionTimeoutMS=5000,
        maxPoolSize=int(os.getenv("MONGO_MAX_POOL", "50")),
        minPoolSize=int(os.getenv("MONGO_MIN_POOL", "5")),
        maxIdleTimeMS=30000,
    )
    _db = _client.invoice_tally
    invoices = _db.invoices
    counters = _db.counters
    users = _db.users
    clients = _db.clients
    banking_rules = _db.banking_rules
    organizations = _db.organizations
    companies = _db.companies
    audit_logs = _db.audit_logs
    journal_lines = _db.journal_lines
    ledger_types = _db.ledger_types
    subscriptions = _db.subscriptions
    plans = _db.plans
    client_users = _db.client_users
    ai_cache = _db.ai_cache

    # Seed counters
    for cname in ("invoice_id", "client_id", "company_id"):
        if not await counters.find_one({"_id": cname}):
            await execute_db_write_with_retry(counters.insert_one, {"_id": cname, "seq": 0})

    await _create_indexes()


async def _create_indexes():
    try:
        # file_hash dedup — stored at TOP LEVEL of invoice doc (not inside extracted)
        await invoices.create_index(
            [("user_id", 1), ("file_hash", 1)],
            unique=True, sparse=True, name="idx_file_hash_dedup",
        )
        await invoices.create_index("display_id", unique=True, name="idx_display_id")
        await invoices.create_index(
            [("user_id", 1), ("created_at", -1)], name="idx_user_dashboard",
        )
        await invoices.create_index(
            [("status", 1), ("priority_sync", -1)], name="idx_tally_polling",
        )
        await invoices.create_index(
            [("user_id", 1), ("client_id", 1), ("created_at", -1)], name="idx_user_client",
        )
        await invoices.create_index(
            [("user_id", 1), ("status", 1), ("created_at", -1)], name="idx_user_status",
        )
        # Period-based reports: fast date-range filtering per company
        await invoices.create_index(
            [("company_id", 1), ("invoice_date", -1)], name="idx_company_date",
        )
        # Vendor lookup: eliminates full collection scans on vendor search
        await invoices.create_index(
            [("vendor_name", 1), ("company_id", 1)], name="idx_vendor_company",
        )
        # Status counts per company: instant dashboard aggregations
        await invoices.create_index(
            [("status", 1), ("company_id", 1)], name="idx_status_company",
        )
        await audit_logs.create_index(
            [("resource_type", 1), ("resource_id", 1), ("created_at", -1)], name="idx_audit_resource",
        )
        await audit_logs.create_index(
            [("user_id", 1), ("created_at", -1)], name="idx_audit_user",
        )
        await audit_logs.create_index(
            [("created_at", 1)], expireAfterSeconds=7776000, name="idx_audit_ttl",
        )
        # Journal lines: derived ledger legs per invoice. Enables Trial Balance,
        # P&L, Balance Sheet without re-parsing Tally XML.
        await journal_lines.create_index(
            [("invoice_id", 1)], name="idx_jl_invoice",
        )
        await journal_lines.create_index(
            [("user_id", 1), ("client_id", 1), ("date", -1)], name="idx_jl_user_client_date",
        )
        await journal_lines.create_index(
            [("company_id", 1), ("ledger", 1)], name="idx_jl_company_ledger",
        )
        await journal_lines.create_index(
            [("user_id", 1), ("reversed", 1), ("date", -1), ("client_id", 1)],
            name="idx_jl_report_query",
        )
        # Ledger -> account type mapping (chart of accounts). Deterministic, stored once.
        await ledger_types.create_index(
            [("company_id", 1), ("ledger", 1)], unique=True, name="idx_lt_company_ledger",
        )
        await users.create_index("email", unique=True, name="idx_user_email")
        await clients.create_index(
            [("user_id", 1), ("client_id", 1)], unique=True, name="idx_client_user",
        )
        await client_users.create_index(
            [("user_id", 1), ("email", 1)], unique=True, name="idx_client_user_email",
        )
        await client_users.create_index(
            [("client_id", 1)], name="idx_client_user_client",
        )
        await plans.create_index("plan_id", unique=True, name="idx_plan_id")
        await subscriptions.create_index(
            [("user_id", 1)], unique=True, name="idx_sub_user",
        )
        await subscriptions.create_index(
            [("razorpay_subscription_id", 1)], unique=True, sparse=True, name="idx_sub_razorpay",
        )
        # AI extraction cache — TTL on cached_at auto-expires after 7 days
        await ai_cache.create_index(
            [("cached_at", 1)], expireAfterSeconds=604800, name="idx_cache_ttl",
        )
    except Exception as e:
        logger.warning("Index creation warning (non-fatal): %s", e)


async def disconnect():
    if _client:
        _client.close()


async def next_id(counter_name: str = "invoice_id") -> int:
    require_connected()
    result = await execute_db_write_with_retry(
        counters.find_one_and_update,
        {"_id": counter_name},
        {"$inc": {"seq": 1}},
        return_document=True,
    )
    return result["seq"]


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

async def create_user(email: str, password_hash: str, name: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "email": email.lower().strip(),
        "password_hash": password_hash,
        "name": name.strip(),
        "role": "user",
        "created_at": now,
        "last_login": now,
        "invoice_count": 0,
    }
    result = await execute_db_write_with_retry(users.insert_one, doc)
    doc["_id"] = result.inserted_id
    return doc


async def find_user(email: str) -> Optional[dict]:
    return await users.find_one({"email": email.lower().strip()})


async def update_user_login(email: str):
    await execute_db_write_with_retry(
        users.update_one,
        {"email": email.lower().strip()},
        {"$set": {"last_login": datetime.now(timezone.utc).isoformat()}},
    )


async def update_user_profile(email: str, updates: dict):
    await execute_db_write_with_retry(
        users.update_one,
        {"email": email.lower().strip()},
        {"$set": updates},
    )


async def save_correction_memory(email: str, description: str, ledger: str):
    key = description.lower().strip()
    await execute_db_write_with_retry(
        users.update_one,
        {"email": email.lower().strip()},
        {"$set": {f"correction_memory.{key}": ledger}},
    )


async def get_correction_memory(email: str) -> dict:
    user = await users.find_one({"email": email.lower().strip()}, {"correction_memory": 1})
    return (user or {}).get("correction_memory") or {}


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

async def create_client(user_id: str, company_name: str, client_name: str, gstin: str = "") -> dict:
    doc = {
        "client_id": await next_id("client_id"),
        "user_id": user_id,
        "company_name": company_name.strip(),
        "client_name": client_name.strip(),
        "gstin": gstin.strip().upper() if gstin else "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "invoice_count": 0,
    }
    result = await execute_db_write_with_retry(clients.insert_one, doc)
    doc["_id"] = result.inserted_id
    return doc


async def list_clients(user_id: str) -> list:
    cursor = clients.find({"user_id": user_id}, sort=[("created_at", -1)])
    return await cursor.to_list(length=1000)


async def get_client(client_id: int) -> Optional[dict]:
    return await clients.find_one({"client_id": client_id})


async def update_client(client_id: int, updates: dict):
    allowed = {"company_name", "client_name", "gstin"}
    clean = {k: v for k, v in updates.items() if k in allowed and v}
    if not clean:
        return
    await execute_db_write_with_retry(
        clients.update_one, {"client_id": client_id}, {"$set": clean}
    )


async def delete_client(client_id: int):
    await execute_db_write_with_retry(clients.delete_one, {"client_id": client_id})
    await execute_db_write_with_retry(invoices.delete_many, {"client_id": client_id})


# ---------------------------------------------------------------------------
# Companies (multi-company config store)
# ---------------------------------------------------------------------------

async def create_company(user_id: str, name: str, gstin: str = "", state_code: str = "",
                         purchase_ledger: str = "Purchase", sales_ledger: str = "Sales",
                         bank_ledger: str = "Bank") -> dict:
    doc = {
        "company_id": await next_id("company_id"),
        "user_id": user_id,
        "company_name": name,
        "company_gstin": gstin.upper() if gstin else "",
        "state_code": state_code,
        "purchase_ledger": purchase_ledger,
        "sales_ledger": sales_ledger,
        "bank_ledger": bank_ledger,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "active": True,
    }
    await execute_db_write_with_retry(companies.insert_one, doc)
    return doc


async def list_companies(user_id: str) -> list:
    if companies is None:
        return []
    cursor = companies.find({"user_id": user_id, "active": True}).sort("company_name", 1)
    return await cursor.to_list(length=50)


async def get_company(company_id: int) -> Optional[dict]:
    if companies is None:
        return None
    return await companies.find_one({"company_id": company_id})


async def update_company(company_id: int, updates: dict):
    if companies is None:
        return
    allowed = {"company_name", "company_gstin", "state_code", "purchase_ledger",
               "sales_ledger", "bank_ledger", "active"}
    clean = {k: v for k, v in updates.items() if k in allowed and v}
    if clean:
        await execute_db_write_with_retry(
            companies.update_one, {"company_id": company_id}, {"$set": clean}
        )


async def delete_company(company_id: int):
    if companies is None:
        return
    await execute_db_write_with_retry(companies.delete_one, {"company_id": company_id})


async def auto_migrate_env_config(user_id: str) -> Optional[int]:
    """Migrate env-var company config into companies collection if no companies exist."""
    if companies is None:
        return None
    existing = await companies.count_documents({"user_id": user_id})
    if existing > 0:
        return None
    env_name = os.getenv("COMPANY_NAME", "")
    if not env_name:
        return None
    doc = await create_company(
        user_id=user_id,
        name=env_name,
        gstin=os.getenv("COMPANY_GSTIN", ""),
        state_code=os.getenv("COMPANY_STATE_CODE", ""),
        purchase_ledger=os.getenv("PURCHASE_LEDGER", "Purchase"),
        sales_ledger=os.getenv("SALES_LEDGER", "Sales"),
        bank_ledger=os.getenv("BANK_LEDGER", "Bank"),
    )
    return doc["company_id"]


# ---------------------------------------------------------------------------
# Banking Rules
# ---------------------------------------------------------------------------

async def list_banking_rules(user_id: str) -> list:
    if banking_rules is None:
        return []
    cursor = banking_rules.find({"user_id": user_id}).sort("keyword", 1)
    return await cursor.to_list(length=200)


async def create_banking_rule(user_id: str, keyword: str, voucher_type: str, target_ledger: str) -> dict:
    doc = {
        "user_id": user_id,
        "keyword": keyword.strip(),
        "voucher_type": voucher_type,
        "target_ledger": target_ledger.strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if banking_rules is not None:
        await execute_db_write_with_retry(banking_rules.insert_one, doc)
    return doc


async def delete_banking_rule(rule_id: str, user_id: str):
    if banking_rules is None:
        return
    await execute_db_write_with_retry(
        banking_rules.delete_one, {"_id": ObjectId(rule_id), "user_id": user_id}
    )


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

async def insert_invoice(
    user_id: str, client_id: int, extracted: dict, validation: dict,
    xml_generated: bool = False, xml_content: str = None, xml_issues: list = None,
    file_hash: str = "", image_data: str = "", company_id: int = None,
    storage_key: str = "", display_id: int = None,
) -> tuple[int, object]:
    doc = {
        "display_id": display_id or await next_id("invoice_id"),
        "user_id": user_id,
        "company_id": company_id,
        "client_id": client_id,
        # FIX: file_hash stored at TOP LEVEL — not inside extracted — so the index works
        "file_hash": file_hash,
        "image_data": image_data if image_data else None,  # kept for backward compat
        "storage_key": storage_key or None,  # new: S3/R2 path, replaces image_data for new invoices
        "created_at": datetime.now(timezone.utc).isoformat(),
        "extracted": extracted,
        "validation": validation,
        "xml_generated": xml_generated,
        "xml_content": xml_content,
        "xml_issues": xml_issues or [],
        "status": "draft",
        "synced_at": None,
        "sync_error": None,
        "item_ledgers": [],
        "reviewed_at": None,
        "reviewed_by": "",
    }
    result = await execute_db_write_with_retry(invoices.insert_one, doc)
    if clients is not None:
        try:
            await execute_db_write_with_retry(
                clients.update_one, {"client_id": client_id}, {"$inc": {"invoice_count": 1}}
            )
        except Exception:
            pass
    return doc["display_id"], result.inserted_id


async def update_invoice(display_id: int, updates: dict):
    await execute_db_write_with_retry(
        invoices.update_one, {"display_id": display_id}, {"$set": updates}
    )


async def update_invoice_status(display_id: int, status: str, sync_error: str = None):
    updates = {"status": status}
    if status == "exported":
        updates["synced_at"] = datetime.now(timezone.utc).isoformat()
    if sync_error:
        updates["sync_error"] = sync_error
    await execute_db_write_with_retry(
        invoices.update_one, {"display_id": display_id}, {"$set": updates}
    )


async def list_pending_sync(user_id: str = None, limit: int = 50) -> list:
    query = {"status": "validated", "xml_content": {"$exists": True, "$ne": None}}
    if user_id:
        query["user_id"] = user_id
    cursor = invoices.find(query).sort([("priority_sync", -1), ("created_at", 1)]).limit(limit)
    return await cursor.to_list(length=limit)


async def get_invoice(display_id: int) -> Optional[dict]:
    return await invoices.find_one({"display_id": display_id})


async def list_invoices(
    user_id: str = None,
    client_id: int = None,
    sort_field: str = "display_id",
    sort_dir: int = -1,
    page: int = 1,
    page_size: int = 100,
) -> list:
    """Paginated invoice listing. page is 1-based. Max 200 per page."""
    page_size = min(page_size, 200)
    query = {}
    if user_id:
        query["user_id"] = user_id
    if client_id is not None:
        query["client_id"] = client_id
    skip = (page - 1) * page_size
    cursor = invoices.find(query, sort=[(sort_field, sort_dir)]).skip(skip).limit(page_size)
    return await cursor.to_list(length=page_size)


async def count_invoices(user_id: str = None, client_id: int = None) -> int:
    query = {}
    if user_id:
        query["user_id"] = user_id
    if client_id is not None:
        query["client_id"] = client_id
    return await invoices.count_documents(query)


async def find_by_file_hash(file_hash: str, user_id: str = None) -> Optional[dict]:
    # FIX: query top-level file_hash field (not extracted.file_hash)
    query = {"file_hash": file_hash}
    if user_id:
        query["user_id"] = user_id
    return await invoices.find_one(query)


async def find_duplicate(vendor: str, inv_no: str, user_id: str = None) -> Optional[dict]:
    """FIX: escape regex metacharacters to prevent ReDoS injection."""
    if not vendor or not inv_no:
        return None
    safe_vendor = re.escape(vendor.strip())
    safe_inv_no = re.escape(inv_no.strip())
    query = {
        "extracted.vendor_name": {"$regex": f"^{safe_vendor}$", "$options": "i"},
        "extracted.invoice_number": {"$regex": f"^{safe_inv_no}$", "$options": "i"},
    }
    if user_id:
        query["user_id"] = user_id
    return await invoices.find_one(query)


async def find_similar_vendors(vendor_name: str, user_id: str = None) -> list[dict]:
    if not vendor_name or invoices is None:
        return []
    name_lower = vendor_name.strip().lower()
    query = {}
    if user_id:
        query["user_id"] = user_id
    cursor = invoices.find(
        query,
        {"extracted.vendor_name": 1, "extracted.gstin": 1, "extracted.vendor_gstin": 1, "created_at": 1},
    ).sort("created_at", -1).limit(100)
    results = await cursor.to_list(length=100)
    seen: set = set()
    similar = []
    for r in results:
        name = (r.get("extracted") or {}).get("vendor_name", "")
        gstin = (r.get("extracted") or {}).get("gstin", "") or (r.get("extracted") or {}).get("vendor_gstin", "")
        nl = name.strip().lower()
        if not nl or nl == name_lower:
            continue
        key = (nl, gstin.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        ratio = difflib.SequenceMatcher(None, name_lower, nl).ratio()
        if ratio >= 0.5:
            similar.append((ratio, {"vendor_name": name, "gstin": gstin, "last_seen": r.get("created_at", "")}))
    similar.sort(key=lambda x: -x[0])
    return [s[1] for s in similar[:5]]


# ---------------------------------------------------------------------------
# Company Analytics
# ---------------------------------------------------------------------------

async def get_company_analytics(company_id: int) -> dict:
    """Aggregate invoice stats for a company: counts by status, monthly trend, top clients."""
    if invoices is None:
        return {"total": 0, "by_status": {}, "monthly_trend": [], "top_clients": []}

    match = {"company_id": company_id}

    # 1. count by status
    pipeline_status = [{"$match": match}, {"$group": {"_id": "$status", "count": {"$sum": 1}}}]
    status_raw = await invoices.aggregate(pipeline_status).to_list(length=20)
    by_status = {s["_id"] or "unknown": s["count"] for s in status_raw}

    # 2. monthly trend — last 12 months
    from bson.son import SON
    pipeline_monthly = [
        {"$match": {**match, "created_at": {"$ne": None}}},
        {"$project": {
            "month": {"$substr": ["$created_at", 0, 7]}
        }},
        {"$group": {"_id": "$month", "count": {"$sum": 1}}},
        {"$sort": SON([("_id", 1)])},
    ]
    monthly_raw = await invoices.aggregate(pipeline_monthly).to_list(length=24)
    monthly_trend = [{"month": m["_id"], "count": m["count"]} for m in monthly_raw]

    # 3. top clients
    pipeline_clients = [
        {"$match": match},
        {"$group": {"_id": "$client_id", "count": {"$sum": 1}}},
        {"$sort": SON([("count", -1)])},
        {"$limit": 5},
    ]
    client_raw = await invoices.aggregate(pipeline_clients).to_list(length=5)
    top_clients_raw = []
    for c in client_raw:
        if clients is not None:
            cl = await clients.find_one({"client_id": c["_id"]}, {"client_name": 1, "company_name": 1})
            name = (cl or {}).get("client_name") or (cl or {}).get("company_name") or f"Client #{c['_id']}"
        else:
            name = f"Client #{c['_id']}"
        top_clients_raw.append({"client_id": c["_id"], "name": name, "count": c["count"]})

    return {
        "total": sum(by_status.values()),
        "by_status": by_status,
        "monthly_trend": monthly_trend,
        "top_clients": top_clients_raw,
    }


# ---------------------------------------------------------------------------
# Audit Logs
# ---------------------------------------------------------------------------

async def insert_audit_log(entry: dict) -> object:
    """Insert an audit log entry. Returns inserted_id."""
    doc = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        **entry,
    }
    if audit_logs is not None:
        result = await execute_db_write_with_retry(audit_logs.insert_one, doc)
        return result.inserted_id
    return None


async def list_audit_logs(
    resource_type: str = None,
    resource_id: str = None,
    user_id: str = None,
    action: str = None,
    limit: int = 100,
) -> list:
    """Query audit logs with optional filters, newest first."""
    query = {}
    if resource_type:
        query["resource_type"] = resource_type
    if resource_id is not None:
        query["resource_id"] = str(resource_id)
    if user_id:
        query["user_id"] = user_id
    if action:
        query["action"] = action
    if audit_logs is not None:
        cursor = audit_logs.find(query).sort("created_at", -1).limit(limit)
        return await cursor.to_list(length=limit)
    return []


async def get_last_audit_event(resource_type: str, resource_id: str, action: str = None) -> Optional[dict]:
    """Return the most recent audit event for a given resource."""
    query = {"resource_type": resource_type, "resource_id": str(resource_id)}
    if action:
        query["action"] = action
    if audit_logs is not None:
        return await audit_logs.find_one(query, sort=[("created_at", -1)])
    return None


# ---------------------------------------------------------------------------
# Journal Lines (derived ledger legs — single source of truth for reporting)
# ---------------------------------------------------------------------------

async def replace_journal_lines(invoice_id: str, lines: list) -> None:
    """Replace all journal lines for an invoice with the freshly generated legs.

    Idempotent: re-generating XML for the same invoice overwrites the legs so
    reports never double-count. Lines must each carry: ledger, debit, credit.
    """
    if journal_lines is None:
        return
    await execute_db_write_with_retry(
        journal_lines.delete_many, {"invoice_id": invoice_id}
    )
    if not lines:
        return
    docs = []
    for i, ln in enumerate(lines):
        docs.append({
            "invoice_id": invoice_id,
            "user_id": ln.get("user_id"),
            "client_id": ln.get("client_id"),
            "company_id": ln.get("company_id"),
            "ledger": ln["ledger"],
            "debit": float(ln.get("debit", 0.0) or 0.0),
            "credit": float(ln.get("credit", 0.0) or 0.0),
            "account_type": ln.get("account_type", "Expense"),
            "voucher_type": ln.get("voucher_type"),
            "date": ln.get("date"),
            "line_no": i,
            "reversed": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    await execute_db_write_with_retry(journal_lines.insert_many, docs)


async def list_journal_lines(invoice_id: str = None, company_id: str = None,
                             user_id: str = None, client_id: str = None,
                             start_date: str = None, end_date: str = None,
                             reversed_filter: bool = False) -> list:
    """Query journal lines with optional filters.

    If reversed_filter=True, only non-reversed entries are returned.
    Report queries should always use reversed_filter=True so the
    idx_jl_report_query index is fully utilised.
    """
    query = {}
    if invoice_id:
        query["invoice_id"] = invoice_id
    if company_id:
        query["company_id"] = company_id
    if user_id:
        query["user_id"] = user_id
    if client_id:
        query["client_id"] = client_id
    if reversed_filter:
        query["reversed"] = False
    if start_date or end_date:
        query["date"] = {}
        if start_date:
            query["date"]["$gte"] = start_date
        if end_date:
            query["date"]["$lte"] = end_date
    if journal_lines is not None:
        cursor = journal_lines.find(query, max_time_ms=30000).sort("date", 1)
        return await cursor.to_list(length=50000)
    return []


async def set_journal_line_reversed(invoice_id: str, reversed: bool = True) -> int:
    """Mark all journal lines of an invoice as reversed (immutable reversal, not delete)."""
    if journal_lines is None:
        return 0
    result = await execute_db_write_with_retry(
        journal_lines.update_many,
        {"invoice_id": invoice_id},
        {"$set": {"reversed": reversed}},
    )
    return result.modified_count or 0


# ---------------------------------------------------------------------------
# Ledger Types (chart of accounts: ledger -> account type)
# ---------------------------------------------------------------------------

async def upsert_ledger_type(company_id: str, ledger: str, account_type: str,
                             parent_group: str = None) -> None:
    """Store/refresh the account-type mapping for a ledger under a company."""
    if ledger_types is None:
        return
    await execute_db_write_with_retry(
        ledger_types.update_one,
        {"company_id": company_id, "ledger": ledger},
        {"$set": {
            "company_id": company_id,
            "ledger": ledger,
            "account_type": account_type,
            "parent_group": parent_group,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )


async def get_ledger_type(company_id: str, ledger: str) -> Optional[dict]:
    if ledger_types is None:
        return None
    return await ledger_types.find_one({"company_id": company_id, "ledger": ledger})


async def list_ledger_types(company_id: str) -> list:
    if ledger_types is None:
        return []
    cursor = ledger_types.find({"company_id": company_id}, max_time_ms=10000)
    return await cursor.to_list(length=500)


# ---------------------------------------------------------------------------
# Plans & Subscriptions (Razorpay billing)
# ---------------------------------------------------------------------------

DEFAULT_PLANS = [
    {
        "plan_id": "starter",
        "name": "Starter",
        "price": 0,
        "currency": "INR",
        "interval": "month",
        "features": ["50 invoices/month", "1 company", "Basic reports (TB/P&L/BS)"],
        "invoice_limit": 50,
        "company_limit": 1,
        "client_portal": False,
        "razorpay_plan_id": "",
    },
    {
        "plan_id": "professional",
        "name": "Professional",
        "price": 2499,
        "currency": "INR",
        "interval": "month",
        "features": ["500 invoices/month", "3 companies", "Full reports", "Client portal"],
        "invoice_limit": 500,
        "company_limit": 3,
        "client_portal": True,
        "razorpay_plan_id": "",
    },
    {
        "plan_id": "enterprise",
        "name": "Enterprise",
        "price": 9999,
        "currency": "INR",
        "interval": "month",
        "features": ["Unlimited invoices", "Unlimited companies", "Full reports", "Client portal", "Priority support"],
        "invoice_limit": None,
        "company_limit": None,
        "client_portal": True,
        "razorpay_plan_id": "",
    },
]


async def seed_plans():
    if plans is None:
        return
    for plan in DEFAULT_PLANS:
        existing = await plans.find_one({"plan_id": plan["plan_id"]})
        if not existing:
            await execute_db_write_with_retry(plans.insert_one, plan)


async def get_plan(plan_id: str) -> Optional[dict]:
    if plans is None:
        return None
    return await plans.find_one({"plan_id": plan_id}, max_time_ms=5000)


async def list_plans() -> list[dict]:
    if plans is None:
        return []
    cursor = plans.find({}, {"_id": 0}, max_time_ms=5000)
    return await cursor.to_list(length=100)


async def get_subscription(user_id: str) -> Optional[dict]:
    if subscriptions is None:
        return None
    return await subscriptions.find_one({"user_id": user_id}, max_time_ms=5000)


async def upsert_subscription(user_id: str, data: dict) -> None:
    if subscriptions is None:
        return
    data["user_id"] = user_id
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    await execute_db_write_with_retry(
        subscriptions.update_one,
        {"user_id": user_id},
        {"$set": data},
        upsert=True,
    )


async def update_subscription_razorpay(user_id: str, sub_id: str, status: str) -> None:
    if subscriptions is None:
        return
    await execute_db_write_with_retry(
        subscriptions.update_one,
        {"user_id": user_id},
        {"$set": {
            "razorpay_subscription_id": sub_id,
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )


# ---------------------------------------------------------------------------
# Client Users (portal login for CA's clients)
# ---------------------------------------------------------------------------

async def create_client_user(email: str, password_hash: str, name: str,
                             user_id: str, client_id: int) -> dict:
    if client_users is None:
        return {}
    doc = {
        "email": email.lower().strip(),
        "password_hash": password_hash,
        "name": name.strip(),
        "user_id": user_id,
        "client_id": client_id,
        "role": "client",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_login": datetime.now(timezone.utc).isoformat(),
    }
    result = await execute_db_write_with_retry(client_users.insert_one, doc)
    doc["_id"] = str(result.inserted_id)
    return doc


async def get_client_user(email: str) -> Optional[dict]:
    if client_users is None:
        return None
    return await client_users.find_one({"email": email.lower().strip()}, max_time_ms=5000)


async def get_client_users_for_ca(user_id: str) -> list[dict]:
    if client_users is None:
        return []
    cursor = client_users.find({"user_id": user_id}, max_time_ms=5000)
    return await cursor.to_list(length=1000)
