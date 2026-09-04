"""
core.exceptions
================
OOP exception hierarchy for MailGuard.

Every exception carries a structured error code (``MG-xxxx``), a severity
level, a UTC timestamp, and an optional context payload so failures can be
logged, filtered, and audited consistently across the whole application.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class Severity(enum.Enum):
    """Severity classification attached to every MailGuard exception."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class MailGuardError(Exception):
    """
    Base class for every exception raised by MailGuard.

    Attributes:
        message: Human readable description of the failure.
        code: Project-prefixed structured error code, e.g. ``MG-1001``.
        severity: :class:`Severity` classification of the failure.
        timestamp: UTC timestamp captured at raise time.
        context: Arbitrary structured data useful for audit logging.
    """

    default_code: str = "MG-1000"
    default_severity: Severity = Severity.ERROR

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        severity: Optional[Severity] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code
        self.severity = severity or self.default_severity
        self.timestamp = datetime.now(timezone.utc)
        self.context: Dict[str, Any] = context or {}
        self.__cause__ = cause

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the exception into a JSON-friendly audit record."""
        return {
            "code": self.code,
            "severity": str(self.severity),
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "context": self.context,
            "type": type(self).__name__,
        }

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(code={self.code!r}, "
            f"severity={str(self.severity)!r}, message={self.message!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MailGuardError):
            return NotImplemented
        return (self.code, self.message) == (other.code, other.message)

    def __hash__(self) -> int:
        return hash((self.code, self.message))


# --------------------------------------------------------------------------
# Configuration errors
# --------------------------------------------------------------------------

class ConfigError(MailGuardError):
    default_code = "MG-1100"


class ConfigNotFoundError(ConfigError):
    default_code = "MG-1101"


class ConfigDecryptionError(ConfigError):
    default_code = "MG-1102"
    default_severity = Severity.CRITICAL


class ConfigValidationError(ConfigError):
    default_code = "MG-1103"


class MissingPassphraseError(ConfigError):
    default_code = "MG-1104"
    default_severity = Severity.CRITICAL


# --------------------------------------------------------------------------
# Validation errors
# --------------------------------------------------------------------------

class ValidationError(MailGuardError):
    default_code = "MG-1200"


class InvalidEmailError(ValidationError):
    default_code = "MG-1201"


class SuspiciousEmailPatternError(ValidationError):
    default_code = "MG-1202"
    default_severity = Severity.WARNING


class InvalidScheduleTimeError(ValidationError):
    default_code = "MG-1203"


# --------------------------------------------------------------------------
# Attachment errors
# --------------------------------------------------------------------------

class AttachmentError(MailGuardError):
    default_code = "MG-1300"


class AttachmentNotFoundError(AttachmentError):
    default_code = "MG-1301"


class AttachmentTooLargeError(AttachmentError):
    default_code = "MG-1302"


class UnsupportedAttachmentTypeError(AttachmentError):
    default_code = "MG-1303"


# --------------------------------------------------------------------------
# Template errors
# --------------------------------------------------------------------------

class TemplateError(MailGuardError):
    default_code = "MG-1400"


class TemplateNotFoundError(TemplateError):
    default_code = "MG-1401"


class TemplateRenderError(TemplateError):
    default_code = "MG-1402"


# --------------------------------------------------------------------------
# SMTP / delivery errors
# --------------------------------------------------------------------------

class SMTPConnectionError(MailGuardError):
    default_code = "MG-1500"
    default_severity = Severity.CRITICAL


class SMTPAuthenticationError(SMTPConnectionError):
    default_code = "MG-1501"


class SMTPSendError(MailGuardError):
    default_code = "MG-1502"


class RecipientRefusedError(SMTPSendError):
    default_code = "MG-1503"


class DeliveryTimeoutError(SMTPSendError):
    default_code = "MG-1504"


# --------------------------------------------------------------------------
# Scheduler / concurrency errors
# --------------------------------------------------------------------------

class SchedulerError(MailGuardError):
    default_code = "MG-1600"


class JobAlreadyExistsError(SchedulerError):
    default_code = "MG-1601"
    default_severity = Severity.WARNING


class JobNotFoundError(SchedulerError):
    default_code = "MG-1602"
    default_severity = Severity.WARNING


class WorkerPoolError(MailGuardError):
    default_code = "MG-1700"
    default_severity = Severity.CRITICAL
