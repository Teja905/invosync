"""Audit logging for InvoSync.

Tracks sensitive operations:
- Authentication (login, signup, logout)
- Invoice operations (extract, generate, sync, replay)
- Configuration changes
- Data mutations (corrections, ledger mappings)
- Admin actions
"""

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("invosync.audit")


class AuditLogger:
    """Structured audit logger for compliance and security."""

    @staticmethod
    def log_auth(action: str, email: str, success: bool, ip: Optional[str] = None, details: Optional[str] = None):
        """Log authentication events."""
        logger.info(
            "AUDIT auth action=%s email=%s success=%s ip=%s details=%s",
            action, email, success, ip or "-", details or "-"
        )

    @staticmethod
    def log_invoice_action(action: str, invoice_id: int, user_id: str, details: Optional[str] = None):
        """Log invoice operations."""
        logger.info(
            "AUDIT invoice action=%s invoice_id=%d user_id=%s details=%s",
            action, invoice_id, user_id, details or "-"
        )

    @staticmethod
    def log_config_change(user_id: str, field: str, old_value: str, new_value: str):
        """Log configuration changes."""
        logger.info(
            "AUDIT config_change user_id=%s field=%s old=%s new=%s",
            user_id, field, old_value or "-", new_value or "-"
        )

    @staticmethod
    def log_correction(user_id: str, description: str, ledger: str, source: str = "manual"):
        """Log ledger corrections."""
        logger.info(
            "AUDIT correction user_id=%s description=%s ledger=%s source=%s",
            user_id, description, ledger, source
        )

    @staticmethod
    def log_sync(user_id: str, invoice_id: int, success: bool, error: Optional[str] = None):
        """Log sync attempts."""
        logger.info(
            "AUDIT sync user_id=%s invoice_id=%d success=%s error=%s",
            user_id, invoice_id, success, error or "-"
        )

    @staticmethod
    def log_admin(action: str, admin_email: str, target: str, details: Optional[str] = None):
        """Log admin actions."""
        logger.info(
            "AUDIT admin action=%s admin=%s target=%s details=%s",
            action, admin_email, target, details or "-"
        )

    @staticmethod
    def log_data_access(user_id: str, resource: str, resource_id: str, action: str = "read"):
        """Log data access for compliance."""
        logger.info(
            "AUDIT access user_id=%s resource=%s resource_id=%s action=%s",
            user_id, resource, resource_id, action
        )


# Global audit logger instance
audit = AuditLogger()
