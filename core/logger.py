"""
core.logger
===========
Non-blocking logging built on ``logging.handlers.QueueHandler`` /
``QueueListener`` so that disk and console I/O never stalls the async
event loop. Provides two sinks:

* Console  - human readable, ANSI colour coded by level.
* Audit    - JSON-lines file, one structured record per event, suitable
             for SIEM ingestion and accountability trails.
"""

from __future__ import annotations

import atexit
import json
import logging
import logging.handlers
import queue
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class _AnsiColorFormatter(logging.Formatter):
    """Console formatter that colours the level name using ANSI codes."""

    _COLORS = {
        logging.DEBUG: "\033[36m",     # cyan
        logging.INFO: "\033[32m",      # green
        logging.WARNING: "\033[33m",   # yellow
        logging.ERROR: "\033[31m",     # red
        logging.CRITICAL: "\033[1;41m",  # bold white on red
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self._COLORS.get(record.levelno, "")
        base = super().format(record)
        if sys.stderr.isatty():
            return f"{color}{base}{self._RESET}"
        return base


class _JsonLinesFormatter(logging.Formatter):
    """Audit formatter emitting one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        extra_code = getattr(record, "error_code", None)
        if extra_code:
            payload["error_code"] = extra_code
        extra_ctx = getattr(record, "context", None)
        if extra_ctx:
            payload["context"] = extra_ctx
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class LoggerFactory:
    """
    Builds and caches the application logger.

    A single background :class:`~logging.handlers.QueueListener` thread
    drains a thread/coroutine-safe queue and fans records out to the
    console and audit-file handlers, keeping producers non-blocking.
    """

    _configured = False
    _listener: Optional[logging.handlers.QueueListener] = None

    @classmethod
    def configure(
        cls,
        log_dir: str = "logs",
        audit_filename: str = "mailguard_audit.jsonl",
        level: int = logging.INFO,
    ) -> logging.Logger:
        logger = logging.getLogger("mailguard")
        if cls._configured:
            return logger

        Path(log_dir).mkdir(parents=True, exist_ok=True)
        audit_path = Path(log_dir) / audit_filename

        log_queue: "queue.Queue[logging.LogRecord]" = queue.Queue(-1)
        queue_handler = logging.handlers.QueueHandler(log_queue)
        logger.addHandler(queue_handler)
        logger.setLevel(level)
        logger.propagate = False

        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(
            _AnsiColorFormatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
        )

        audit_handler = logging.handlers.RotatingFileHandler(
            audit_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        audit_handler.setFormatter(_JsonLinesFormatter())

        listener = logging.handlers.QueueListener(
            log_queue, console_handler, audit_handler, respect_handler_level=True
        )
        listener.start()
        cls._listener = listener
        cls._configured = True
        atexit.register(cls.shutdown)
        return logger

    @classmethod
    def shutdown(cls) -> None:
        if cls._listener is not None:
            cls._listener.stop()
            cls._listener = None
            cls._configured = False


def get_logger() -> logging.Logger:
    """Return the configured MailGuard logger, configuring on first use."""
    return LoggerFactory.configure()


def log_exception(logger: logging.Logger, exc: Exception) -> None:
    """Log a :class:`~core.exceptions.MailGuardError` with full context."""
    code = getattr(exc, "code", "MG-0000")
    context = getattr(exc, "context", {})
    logger.error(str(exc), extra={"error_code": code, "context": context}, exc_info=exc)
