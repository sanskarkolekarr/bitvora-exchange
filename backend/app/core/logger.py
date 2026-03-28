"""
Structured logging system.
Provides JSON-formatted logs with timestamp, level, module, and message.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from typing import Any


class StructuredFormatter(logging.Formatter):
    """
    Produces structured log lines:
    [2026-03-27T17:00:00Z] [INFO] [core.database] Connection pool initialised
    """

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        )[:-3] + "Z"
        level = record.levelname.ljust(8)
        module = record.name
        msg = record.getMessage()

        base = f"[{ts}] [{level}] [{module}] {msg}"

        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            base += f"\n{record.exc_text}"

        return base


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Create or retrieve a structured logger.

    Args:
        name: Logger name (usually __name__ or a dotted module path).
        level: Minimum log level.

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(name)

    # Avoid duplicate handlers on repeated calls
    if logger.handlers:
        return logger

    logger.setLevel(level)
    logger.propagate = False

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(StructuredFormatter())
    logger.addHandler(handler)

    return logger


# Package-level root logger
_root = get_logger("bitvora", logging.INFO)
