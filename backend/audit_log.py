"""Audit logging for InvoSync — DB-backed with stdout fallback.

Tracks sensitive operations for compliance, undo support, and security review.
Each event is stored in MongoDB's audit_logs collection with a snapshot of
the pre-action state so undo operations can revert cleanly.
"""

import logging
from typing import Optional

logger = logging.getLogger("invosync.audit")


class AuditLogger:
    """Structured audit logger — writes to MongoDB with file fallback."""

    _db = None

    @classmethod
    def _get_db(cls):
        if cls._db is None:
            try:
                import database as db
                cls._db = db
            except Exception:
                cls._db = None
        return cls._db

    @classmethod
    async def _store(cls, entry: dict):
        db_mod = cls._get_db()
        if db_mod and db_mod.audit_logs is not None:
            try:
                await db_mod.insert_audit_log(entry)
                return
            except Exception as exc:
                logger.warning("audit_log DB insert failed, falling back to stdout: %s", exc)
        logger.info("AUDIT %s", " ".join(f"{k}={v}" for k, v in entry.items()))

    @classmethod
    async def log_auth(cls, action: str, email: str, success: bool,
                       ip: Optional[str] = None, details: Optional[str] = None):
        await cls._store({
            "action": f"auth_{action}",
            "resource_type": "auth",
            "resource_id": email,
            "user_id": email,
            "success": success,
            "ip": ip or "",
            "details": details or "",
        })

    @classmethod
    async def log_invoice_action(cls, action: str, invoice_id: int, user_id: str,
                                 details: Optional[str] = None,
                                 snapshot: Optional[dict] = None):
        entry = {
            "action": action,
            "resource_type": "invoice",
            "resource_id": str(invoice_id),
            "user_id": user_id,
            "details": details or "",
        }
        if snapshot:
            entry["snapshot"] = snapshot
        await cls._store(entry)

    @classmethod
    async def log_config_change(cls, user_id: str, field: str,
                                old_value: str, new_value: str):
        await cls._store({
            "action": "config_change",
            "resource_type": "config",
            "resource_id": user_id,
            "user_id": user_id,
            "field": field,
            "old_value": old_value or "",
            "new_value": new_value or "",
        })

    @classmethod
    async def log_correction(cls, user_id: str, description: str,
                             ledger: str, source: str = "manual"):
        await cls._store({
            "action": "correction",
            "resource_type": "correction",
            "resource_id": user_id,
            "user_id": user_id,
            "description": description,
            "ledger": ledger,
            "source": source,
        })

    @classmethod
    async def log_sync(cls, user_id: str, invoice_id: int,
                       success: bool, error: Optional[str] = None):
        await cls._store({
            "action": "sync",
            "resource_type": "sync",
            "resource_id": str(invoice_id),
            "user_id": user_id,
            "success": success,
            "error": error or "",
        })

    @classmethod
    async def log_admin(cls, action: str, admin_email: str, target: str,
                        details: Optional[str] = None):
        await cls._store({
            "action": f"admin_{action}",
            "resource_type": "admin",
            "resource_id": target,
            "user_id": admin_email,
            "details": details or "",
        })

    @classmethod
    async def log_data_access(cls, user_id: str, resource: str,
                              resource_id: str, action: str = "read"):
        await cls._store({
            "action": f"access_{action}",
            "resource_type": resource,
            "resource_id": resource_id,
            "user_id": user_id,
        })

    @classmethod
    async def get_history(cls, resource_type: str = None, resource_id: str = None,
                          user_id: str = None, action: str = None,
                          limit: int = 100) -> list:
        db_mod = cls._get_db()
        if db_mod and db_mod.audit_logs is not None:
            try:
                return await db_mod.list_audit_logs(
                    resource_type=resource_type, resource_id=resource_id,
                    user_id=user_id, action=action, limit=limit,
                )
            except Exception as exc:
                logger.warning("audit_log query failed: %s", exc)
        return []

    @classmethod
    async def get_last_event(cls, resource_type: str, resource_id: str,
                             action: str = None) -> Optional[dict]:
        db_mod = cls._get_db()
        if db_mod and db_mod.audit_logs is not None:
            try:
                return await db_mod.get_last_audit_event(resource_type, resource_id, action)
            except Exception as exc:
                logger.warning("audit_log get_last_event failed: %s", exc)
        return None


audit = AuditLogger
