"""Encryption utilities for sensitive data at rest.

Uses Fernet symmetric encryption (AES-128-CBC + HMAC).
Key is derived from ENCRYPTION_KEY env var.
"""

import os
import base64
import hashlib
import logging
from typing import Optional

logger = logging.getLogger("invosync.crypto")

try:
    from cryptography.fernet import Fernet, InvalidToken
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False


def _get_key() -> Optional[bytes]:
    """Get or derive encryption key from env var."""
    if not _HAS_CRYPTO:
        return None
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        import secrets
        key = secrets.token_urlsafe(32)
        logger.warning("ENCRYPTION_KEY not set — generated ephemeral key. Set ENCRYPTION_KEY env var for production.")
    if len(key) < 32:
        key = hashlib.sha256(key.encode()).digest()
    return base64.urlsafe_b64encode(key[:32].ljust(32, b"0"))


def encrypt(plaintext: str) -> str:
    """Encrypt a string. Returns base64-encoded ciphertext."""
    if not plaintext:
        return plaintext
    key = _get_key()
    if not key:
        return plaintext
    try:
        f = Fernet(key)
        return f.encrypt(plaintext.encode()).decode()
    except Exception:
        return plaintext


def decrypt(ciphertext: str) -> str:
    """Decrypt a base64-encoded ciphertext."""
    if not ciphertext:
        return ciphertext
    key = _get_key()
    if not key:
        return ciphertext
    try:
        f = Fernet(key)
        return f.decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception):
        return ciphertext


def is_encrypted(value: str) -> bool:
    """Check if a string looks like Fernet ciphertext."""
    if not value or not _HAS_CRYPTO:
        return False
    try:
        decoded = base64.urlsafe_b64decode(value + "==")
        return decoded.startswith(b"\x80") or decoded[:4] in (b"gAAAA", b"gAAAB")
    except Exception:
        return False
