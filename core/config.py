"""
core.config
===========
Encrypted configuration management. Configuration at rest is protected
with Fernet symmetric encryption using a key derived from a passphrase
via PBKDF2-HMAC-SHA256 (100,000 iterations, per-install random salt).

Blocking file I/O is offloaded to a thread executor via
``asyncio.to_thread`` so the manager is safe to call from async code
without stalling the event loop.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken

from core.exceptions import (
    ConfigDecryptionError,
    ConfigNotFoundError,
    ConfigValidationError,
    MissingPassphraseError,
)
from core.logger import get_logger

logger = get_logger()

REQUIRED_KEYS = ("smtp_server", "smtp_port", "smtp_username", "smtp_password")


@dataclass(frozen=True)
class SMTPConfig:
    """Immutable, validated view of the SMTP configuration."""

    smtp_server: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    default_sender: str = ""
    smtp_ssl: bool = True
    max_concurrent_sends: int = 5
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not (0 < self.smtp_port < 65536):
            raise ConfigValidationError(
                f"smtp_port out of range: {self.smtp_port}",
                context={"smtp_port": self.smtp_port},
            )

    def __repr__(self) -> str:
        return (
            f"SMTPConfig(server={self.smtp_server!r}, port={self.smtp_port}, "
            f"username={self.smtp_username!r}, password='***redacted***')"
        )

    def __str__(self) -> str:  # avoid leaking the secret in casual prints
        return self.__repr__()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SMTPConfig":
        missing = [k for k in REQUIRED_KEYS if k not in data]
        if missing:
            raise ConfigValidationError(
                f"Missing required configuration keys: {missing}",
                context={"missing_keys": missing},
            )
        known = {
            "smtp_server", "smtp_port", "smtp_username", "smtp_password",
            "default_sender", "smtp_ssl", "max_concurrent_sends",
        }
        extra = {k: v for k, v in data.items() if k not in known}
        return cls(
            smtp_server=data["smtp_server"],
            smtp_port=int(data["smtp_port"]),
            smtp_username=data["smtp_username"],
            smtp_password=data["smtp_password"],
            default_sender=data.get("default_sender", data["smtp_username"]),
            smtp_ssl=bool(data.get("smtp_ssl", True)),
            max_concurrent_sends=int(data.get("max_concurrent_sends", 5)),
            extra=extra,
        )


class ConfigManager:
    """Loads, decrypts, validates, and persists MailGuard configuration."""

    PBKDF2_ITERATIONS = 100_000

    def __init__(
        self,
        config_path: str = "config.json.enc",
        key_salt_path: str = "config.salt",
    ) -> None:
        self.config_path = Path(config_path)
        self.key_salt_path = Path(key_salt_path)
        self._config: Optional[SMTPConfig] = None

    def __repr__(self) -> str:
        return f"ConfigManager(config_path={self.config_path!s})"

    @property
    def config(self) -> SMTPConfig:
        if self._config is None:
            raise ConfigValidationError("Configuration has not been loaded yet")
        return self._config

    def _salt(self) -> bytes:
        if self.key_salt_path.exists():
            return self.key_salt_path.read_bytes()
        salt = os.urandom(16)
        self.key_salt_path.write_bytes(salt)
        os.chmod(self.key_salt_path, 0o600)
        return salt

    def _derive_key(self, passphrase: str) -> bytes:
        import base64

        raw = hashlib.pbkdf2_hmac(
            "sha256", passphrase.encode("utf-8"), self._salt(), self.PBKDF2_ITERATIONS
        )
        return base64.urlsafe_b64encode(raw)

    def _passphrase(self) -> str:
        passphrase = os.getenv("MAILGUARD_PASSPHRASE")
        if not passphrase:
            raise MissingPassphraseError(
                "MAILGUARD_PASSPHRASE environment variable is not set"
            )
        return passphrase

    # -- synchronous primitives -------------------------------------------------

    def _load_sync(self) -> SMTPConfig:
        if not self.config_path.exists():
            raise ConfigNotFoundError(
                f"Configuration file not found: {self.config_path}",
                context={"path": str(self.config_path)},
            )
        fernet = Fernet(self._derive_key(self._passphrase()))
        try:
            encrypted = self.config_path.read_bytes()
            decrypted = fernet.decrypt(encrypted)
        except InvalidToken as exc:
            raise ConfigDecryptionError(
                "Failed to decrypt configuration - wrong passphrase or corrupted file",
                cause=exc,
            ) from exc
        data = json.loads(decrypted.decode("utf-8"))
        self._config = SMTPConfig.from_dict(data)
        logger.info("Configuration loaded and validated", extra={"context": {"path": str(self.config_path)}})
        return self._config

    def _save_sync(self, data: Dict[str, Any]) -> None:
        fernet = Fernet(self._derive_key(self._passphrase()))
        encrypted = fernet.encrypt(json.dumps(data).encode("utf-8"))
        if self.config_path.exists():
            backup = self.config_path.with_name(
                self.config_path.name + f".bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            )
            self.config_path.replace(backup)
            logger.info("Existing configuration backed up", extra={"context": {"backup": str(backup)}})
        self.config_path.write_bytes(encrypted)
        os.chmod(self.config_path, 0o600)
        self._config = SMTPConfig.from_dict(data)

    # -- async wrappers -----------------------------------------------------

    async def load(self) -> SMTPConfig:
        """Load and decrypt configuration off the event loop thread."""
        return await asyncio.to_thread(self._load_sync)

    async def save(self, data: Dict[str, Any]) -> None:
        """Validate, encrypt, and persist configuration atomically."""
        SMTPConfig.from_dict(data)  # validate before writing
        await asyncio.to_thread(self._save_sync, data)
        logger.info("Configuration saved")
