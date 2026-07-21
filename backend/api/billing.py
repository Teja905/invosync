"""Billing & Subscription API — Razorpay integration for plan management."""

import hashlib
import hmac
import logging
import os

import razorpay
from fastapi import APIRouter, Depends, HTTPException, Request

import database as db
from api.deps import get_authenticated_user

logger = logging.getLogger("invosync.billing")

router = APIRouter(prefix="/api/v3/billing", tags=["billing"])

_RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
_RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
_RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

_client = None


def _get_razorpay():
    global _client
    if _client is None and _RAZORPAY_KEY_ID and _RAZORPAY_KEY_SECRET:
        _client = razorpay.Client(auth=(_RAZORPAY_KEY_ID, _RAZORPAY_KEY_SECRET))
    return _client


@router.get("/plans")
async def list_plans(user: dict = Depends(get_authenticated_user)):
    plans = await db.list_plans()
    return {"plans": plans}


@router.get("/subscription")
async def get_subscription(user: dict = Depends(get_authenticated_user)):
    sub = await db.get_subscription(user["user_id"])
    if not sub:
        plan = await db.get_plan("starter")
        return {"subscription": None, "plan": plan, "active": False}
    plan = await db.get_plan(sub.get("plan_id", "starter"))
    return {"subscription": sub, "plan": plan, "active": sub.get("status") == "active"}


@router.post("/create-order")
async def create_order(data: dict, user: dict = Depends(get_authenticated_user)):
    client = _get_razorpay()
    if not client:
        raise HTTPException(400, "Razorpay not configured — set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET")
    plan_id = data.get("plan_id")
    if not plan_id:
        raise HTTPException(400, "plan_id required")
    plan = await db.get_plan(plan_id)
    if not plan:
        raise HTTPException(404, f"Plan '{plan_id}' not found")
    if plan["price"] == 0:
        await db.upsert_subscription(user["user_id"], {"plan_id": plan_id, "status": "active"})
        return {"free": True, "plan_id": plan_id}
    try:
        order = client.order.create({
            "amount": int(plan["price"] * 100),
            "currency": "INR",
            "receipt": f"plan_{plan_id}_user_{user['user_id']}",
            "notes": {"user_id": user["user_id"], "plan_id": plan_id},
        })
    except Exception as e:
        logger.error("Razorpay order creation failed: %s", e)
        raise HTTPException(502, f"Payment gateway error: {e}")
    return {"order": order, "key_id": _RAZORPAY_KEY_ID, "plan": plan}


@router.post("/verify-payment")
async def verify_payment(data: dict, user: dict = Depends(get_authenticated_user)):
    razorpay_order_id = data.get("razorpay_order_id")
    razorpay_payment_id = data.get("razorpay_payment_id")
    razorpay_signature = data.get("razorpay_signature")
    plan_id = data.get("plan_id", "professional")
    if not razorpay_order_id or not razorpay_payment_id or not razorpay_signature:
        raise HTTPException(400, "Missing payment verification fields")
    expected = hmac.new(
        _RAZORPAY_KEY_SECRET.encode(),
        f"{razorpay_order_id}|{razorpay_payment_id}".encode(),
        hashlib.sha1,
    ).hexdigest()
    if razorpay_signature != expected:
        raise HTTPException(400, "Payment signature mismatch — verification failed")
    await db.upsert_subscription(user["user_id"], {
        "plan_id": plan_id,
        "status": "active",
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": razorpay_payment_id,
    })
    return {"verified": True, "plan_id": plan_id}


@router.post("/webhook")
async def razorpay_webhook(request: Request):
    client = _get_razorpay()
    if not client:
        raise HTTPException(500, "Razorpay not configured")
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    if _RAZORPAY_WEBHOOK_SECRET:
        expected = hmac.new(
            _RAZORPAY_WEBHOOK_SECRET.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        if signature != expected:
            raise HTTPException(400, "Invalid webhook signature")
    try:
        event = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    event_type = event.get("event", "")
    payload = event.get("payload", {}).get("subscription", {}).get("entity", {})
    sub_id = payload.get("id", "")
    notes = payload.get("notes", {})
    user_id = notes.get("user_id", "")
    status_map = {
        "subscription.activated": "active",
        "subscription.completed": "completed",
        "subscription.pending": "pending",
        "subscription.halted": "halted",
        "subscription.cancelled": "cancelled",
    }
    new_status = status_map.get(event_type, "")
    if user_id and new_status:
        await db.update_subscription_razorpay(user_id, sub_id, new_status)
        logger.info("Razorpay webhook: user=%s sub=%s status=%s", user_id, sub_id, new_status)
    return {"status": "ok"}
