import logging
import sys
import uuid
from contextvars import ContextVar

from core.pii import PIIRedactingFilter

_request_id: ContextVar[str] = ContextVar("request_id", default="-")

_loggers = {}


class RequestIDFilter(logging.Filter):
    def filter(self, record):
        record.req_id = _request_id.get()
        return True


def set_request_id(rid: str = None):
    """Set the request id for the current async context."""
    _request_id.set(rid or uuid.uuid4().hex[:12])


def get_request_id() -> str:
    return _request_id.get()


def get_logger(name: str = None) -> logging.Logger:
    if name in _loggers:
        return _loggers[name]
    logger = logging.getLogger(name or "invosync")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - [%(req_id)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        handler.addFilter(RequestIDFilter())
        handler.addFilter(PIIRedactingFilter())
        logger.addHandler(handler)
    _loggers[name] = logger
    return logger
