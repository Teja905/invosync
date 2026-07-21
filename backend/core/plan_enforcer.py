"""Plan enforcement middleware — checks user's subscription tier before allowing operations.

Every extract, generate, and sync call should check the user's plan limits.
Starter: 50 invoices/month
Professional: 500 invoices/month, up to 3 companies
Enterprise: unlimited
"""

import logging
from datetime import datetime, timezone

import database as db

logger = logging.getLogger("invosync.plan_enforcer")


async def check_invoice_limit(user_id: str) -> tuple[bool, str]:
    """Check if user has hit their monthly invoice limit."""
    sub = await db.get_subscription(user_id)
    plan_id = sub.get("plan_id", "starter") if sub else "starter"
    status = sub.get("status", "active") if sub else "active"
    if status != "active":
        return False, "Subscription is not active. Please renew to continue."
    plan = await db.get_plan(plan_id)
    if not plan:
        return True, ""
    limit = plan.get("invoice_limit")
    if limit is None:
        return True, ""
    now = datetime.now(timezone.utc)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    count = await db.invoices.count_documents({
        "user_id": user_id,
        "created_at": {"$gte": start_of_month.isoformat()},
    })
    if count >= limit:
        return False, f"Monthly invoice limit ({limit}) reached. Upgrade your plan to continue."
    return True, ""


async def check_company_limit(user_id: str) -> tuple[bool, str]:
    """Check if user has hit their company limit."""
    sub = await db.get_subscription(user_id)
    plan_id = sub.get("plan_id", "starter") if sub else "starter"
    status = sub.get("status", "active") if sub else "active"
    if status != "active":
        return False, "Subscription is not active."
    plan = await db.get_plan(plan_id)
    if not plan:
        return True, ""
    limit = plan.get("company_limit")
    if limit is None:
        return True, ""
    count = await db.companies.count_documents({"user_id": user_id})
    if count >= limit:
        return False, f"Company limit ({limit}) reached. Upgrade your plan."
    return True, ""


async def check_client_portal_access(user_id: str) -> tuple[bool, str]:
    """Check if user's plan includes client portal."""
    sub = await db.get_subscription(user_id)
    plan_id = sub.get("plan_id", "starter") if sub else "starter"
    plan = await db.get_plan(plan_id)
    if not plan:
        return True, ""
    if not plan.get("client_portal", False):
        return False, "Client portal requires Professional plan or above."
    return True, ""
