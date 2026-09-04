"""
validators.email_validator
===========================
RFC-5322-style email validation plus heuristic checks for suspicious
patterns (path traversal, executable extensions, embedded whitespace).
Exposes an async generator so batches of addresses can be validated
without blocking, yielding results as they complete.
"""

from __future__ import annotations

import asyncio
import re
from typing import AsyncGenerator, Iterable, List, Tuple

from core.exceptions import InvalidEmailError, SuspiciousEmailPatternError
from core.logger import get_logger

logger = get_logger()

_EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

_SUSPICIOUS_PATTERNS: Tuple[re.Pattern, ...] = (
    re.compile(r"\.(exe|js|bat|cmd|sh|php|py|pl)$", re.IGNORECASE),
    re.compile(r"\s"),
    re.compile(r"\.\.+"),
    re.compile(r"--+"),
    re.compile(r"//+"),
)


class EmailValidator:
    """Stateless validation helpers for email addresses."""

    @staticmethod
    def is_syntactically_valid(address: str) -> bool:
        return bool(address) and isinstance(address, str) and bool(_EMAIL_PATTERN.match(address))

    @staticmethod
    def has_suspicious_pattern(address: str) -> bool:
        return any(pattern.search(address) for pattern in _SUSPICIOUS_PATTERNS)

    @classmethod
    def validate(cls, address: str) -> None:
        """Raise a specific exception if the address is invalid."""
        if not cls.is_syntactically_valid(address):
            raise InvalidEmailError(
                f"Email address failed format validation: {address!r}",
                context={"address": address},
            )
        if cls.has_suspicious_pattern(address):
            raise SuspiciousEmailPatternError(
                f"Email address matched a suspicious pattern: {address!r}",
                context={"address": address},
            )

    @classmethod
    def is_valid(cls, address: str) -> bool:
        try:
            cls.validate(address)
            return True
        except (InvalidEmailError, SuspiciousEmailPatternError):
            return False

    @classmethod
    async def validate_batch(
        cls, addresses: Iterable[str]
    ) -> AsyncGenerator[Tuple[str, bool, str], None]:
        """
        Yield ``(address, is_valid, reason)`` for each address, ceding
        control back to the event loop between checks so a large
        recipient list never monopolises the loop.
        """
        for address in addresses:
            await asyncio.sleep(0)
            try:
                cls.validate(address)
                yield address, True, ""
            except (InvalidEmailError, SuspiciousEmailPatternError) as exc:
                logger.warning(str(exc), extra={"error_code": exc.code, "context": exc.context})
                yield address, False, exc.message

    @classmethod
    async def validate_all(cls, addresses: Iterable[str]) -> List[str]:
        """Validate every address, raising on the first failure found."""
        invalid: List[str] = []
        async for address, ok, _reason in cls.validate_batch(addresses):
            if not ok:
                invalid.append(address)
        if invalid:
            raise InvalidEmailError(
                f"{len(invalid)} recipient address(es) failed validation",
                context={"invalid_addresses": invalid},
            )
        return list(addresses)
