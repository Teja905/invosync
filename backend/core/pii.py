"""PII redaction — keep personal/business data out of logs and away from third-party AI.

InvoSync handles chartered-accountant data: vendor GSTINs, client names, invoice
amounts, addresses. None of that belongs in application logs or in prompts sent to
external AI providers. These helpers mask identifiable values before they reach a
log line or an outbound request body.
"""

import re

# 15-char GSTIN: 2 digits + 10 alnum + 1 digit + Z + 1 alnum/digit
_GSTIN_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}\d[Zz]{1}[A-Za-z\d]{1}\b")
# PAN: 5 letters + 4 digits + 1 letter
_PAN_RE = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
# Aadhaar: 12 digits, optionally spaced
_AADHAAR_RE = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")
# Email
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
# Indian phone (10 digits, optional +91 / 0 prefix)
_PHONE_RE = re.compile(r"(?:\+?91[\s-]?|0)?\d{10}\b")
# IFSC: 4 letters + 0 + 6 digits
_IFSC_RE = re.compile(r"\b[A-Z]{4}0\d{6}\b")


def _mask(match: re.Match, keep: int = 4) -> str:
    val = match.group(0)
    if len(val) <= keep:
        return "X" * len(val)
    return val[:keep] + "X" * (len(val) - keep)


def redact_pii(text: str) -> str:
    """Return *text* with GSTIN/PAN/Aadhaar/email/phone/IFSC masked.

    Safe to call on any string; non-strings pass through unchanged.
    """
    if not isinstance(text, str):
        return text
    text = _GSTIN_RE.sub(lambda m: _mask(m, 4), text)
    text = _PAN_RE.sub(lambda m: _mask(m, 3), text)
    text = _AADHAAR_RE.sub(lambda m: _mask(m, 4), text)
    text = _EMAIL_RE.sub(lambda m: _mask(m, 2), text)
    text = _PHONE_RE.sub(lambda m: _mask(m, 3), text)
    text = _IFSC_RE.sub(lambda m: _mask(m, 4), text)
    return text


class PIIRedactingFilter:
    """logging.Filter that redacts PII from every record's message."""

    def filter(self, record: "logging.LogRecord") -> bool:  # type: ignore[name-defined]
        if isinstance(getattr(record, "msg", None), str):
            record.msg = redact_pii(record.msg)
        args = getattr(record, "args", None)
        if isinstance(args, tuple) and args:
            record.args = tuple(redact_pii(a) if isinstance(a, str) else a for a in args)
        return True
