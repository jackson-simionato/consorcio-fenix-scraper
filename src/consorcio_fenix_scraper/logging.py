from __future__ import annotations

import logging
import os


PACKAGE_LOGGER_NAME = "consorcio_fenix_scraper"
DEFAULT_LOG_LEVEL = "INFO"
_HANDLER_MARKER = "_consorcio_fenix_console_handler"
_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(level: str | None = None) -> None:
    requested_level = level or os.getenv("LOG_LEVEL") or DEFAULT_LOG_LEVEL
    resolved_level = _resolve_level(requested_level)

    package_logger = logging.getLogger(PACKAGE_LOGGER_NAME)
    _ensure_console_handler(package_logger)
    package_logger.setLevel(resolved_level)
    package_logger.propagate = True

    if resolved_level == logging.INFO and requested_level.upper() not in logging.getLevelNamesMapping():
        package_logger.warning("Invalid LOG_LEVEL='%s'; falling back to INFO", requested_level)


def get_logger(name: str) -> logging.Logger:
    if name == PACKAGE_LOGGER_NAME or name.startswith(f"{PACKAGE_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{PACKAGE_LOGGER_NAME}.{name}")


def _resolve_level(level: str) -> int:
    normalized = level.upper()
    return logging.getLevelNamesMapping().get(normalized, logging.INFO)


def _ensure_console_handler(logger: logging.Logger) -> None:
    for handler in logger.handlers:
        if getattr(handler, _HANDLER_MARKER, False):
            handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
            return

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    setattr(handler, _HANDLER_MARKER, True)
    logger.addHandler(handler)
