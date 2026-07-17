"""Quota / rate-limit detection in the extraction pipeline."""

from extractors import is_quota_error, QUOTA_ERROR_MESSAGE


def test_quota_detected_gemini_resource_exhausted():
    class FakeExc(Exception):
        pass
    e = FakeExc("429 RESOURCE_EXHAUSTED: quota exceeded for gemini-2.0-flash")
    assert is_quota_error(e) is True


def test_quota_detected_openrouter_429():
    e = RuntimeError("OpenRouter quota/limit: {\"error\":{\"code\":429}}")
    assert is_quota_error(e) is True


def test_quota_detected_billing():
    e = RuntimeError("Billing account not configured, usage limit reached")
    assert is_quota_error(e) is True


def test_non_quota_not_detected():
    e = RuntimeError("connection reset by peer")
    assert is_quota_error(e) is False


def test_quota_message_is_actionable():
    assert "OPENROUTER_API_KEY" in QUOTA_ERROR_MESSAGE
    assert "billing" in QUOTA_ERROR_MESSAGE
