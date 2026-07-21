"""One-off migration: move invoice images from MongoDB base64 to S3/R2 object storage.

Existing invoices store images as base64 in `image_data` field. This script reads
each, uploads to S3/R2, sets `storage_key`, and removes `image_data` to free MongoDB
storage (the whole reason we moved to object storage).

Usage:
    python scripts/migrate_images_to_s3.py
"""

import asyncio
import base64
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import database as db
from storage import store as storage_store


async def migrate():
    if db.invoices is None:
        print("Database unavailable")
        return
    cursor = db.invoices.find({
        "image_data": {"$exists": True, "$ne": "", "$ne": None},
        "$or": [
            {"storage_key": {"$exists": False}},
            {"storage_key": None},
            {"storage_key": ""},
        ],
    })
    total = done = 0
    async for inv in cursor:
        total += 1
        image_b64 = inv.get("image_data")
        if not image_b64:
            continue
        display_id = inv.get("display_id")
        user_id = inv.get("user_id", "unknown")
        try:
            image_bytes = base64.b64decode(image_b64)
        except Exception as e:
            print(f"  SKIP invoice {display_id}: corrupt base64 ({e})")
            continue
        storage_key = await storage_store(user_id, display_id, image_bytes)
        await db.invoices.update_one(
            {"_id": inv["_id"]},
            {"$set": {"storage_key": storage_key}, "$unset": {"image_data": ""}},
        )
        done += 1
        if done % 100 == 0:
            print(f"  Migrated {done}/{total}...")
    print(f"Migration complete: {done} invoices migrated out of {total}")


if __name__ == "__main__":
    asyncio.run(migrate())
