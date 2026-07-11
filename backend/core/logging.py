import logging
import sys


_loggers = {}


def get_logger(name: str = None) -> logging.Logger:
    if name in _loggers:
        return _loggers[name]
    logger = logging.getLogger(name or "invoSync")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(handler)
    _loggers[name] = logger
    return logger
