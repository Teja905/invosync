"""PII redaction — ensure GSTIN/email/phone are masked and never leak in logs."""

from core.pii import redact_pii, PIIRedactingFilter
import logging


def test_redact_gstin():
    s = redact_pii("vendor_gstin='27AABCU1234F1ZP' company=27AABCU1234F1ZP")
    assert "27AA" in s
    assert "F1ZP" not in s
    assert "XXXX" in s


def test_redact_email():
    s = redact_pii("contact ca@firm.com for details")
    assert "ca@" not in s
    assert "XX" in s


def test_redact_phone():
    s = redact_pii("call 9876543210 now")
    assert "987" in s
    assert "3210" not in s


def test_redact_aadhaar():
    s = redact_pii("aadhaar 1234 5678 9012")
    assert "1234" in s
    assert "9012" not in s


def test_log_filter_redacts_msg():
    f = PIIRedactingFilter()
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "gstin 27AABCU1234F1ZP", None, None)
    assert f.filter(rec) is True
    assert "27AA" in rec.msg
    assert "F1ZP" not in rec.msg


def test_log_filter_redacts_args():
    f = PIIRedactingFilter()
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "vendor %s", ("27AABCU1234F1ZP",), None)
    assert f.filter(rec) is True
    assert "F1ZP" not in rec.args[0]


def test_non_string_passthrough():
    assert redact_pii(12345) == 12345
    assert redact_pii(None) is None
