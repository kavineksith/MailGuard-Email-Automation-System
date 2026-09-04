"""
services.smtp_client
=======================
Async SMTP transport. Uses ``aiosmtplib`` when available for a truly
non-blocking connection; otherwise transparently falls back to running
the stdlib ``smtplib`` client in a worker thread via
``asyncio.to_thread`` so the public interface never blocks the event
loop either way.
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.message import EmailMessage as MimeEmailMessage
from typing import Iterable, Optional

from core.config import SMTPConfig
from core.exceptions import (
    RecipientRefusedError,
    SMTPAuthenticationError,
    SMTPConnectionError,
    SMTPSendError,
)
from core.logger import get_logger

logger = get_logger()

try:
    import aiosmtplib
    _HAS_AIOSMTPLIB = True
except ImportError:  # pragma: no cover - optional dependency
    _HAS_AIOSMTPLIB = False


def _secure_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.verify_mode = ssl.CERT_REQUIRED
    return context


class AsyncSMTPClient:
    """Sends already-built MIME messages over an authenticated TLS session."""

    def __init__(self, config: SMTPConfig, timeout: float = 15.0) -> None:
        self.config = config
        self.timeout = timeout

    def __repr__(self) -> str:
        return f"AsyncSMTPClient(server={self.config.smtp_server}, port={self.config.smtp_port})"

    async def send(self, mime_message, all_recipients: Iterable[str]) -> None:
        if _HAS_AIOSMTPLIB:
            await self._send_native(mime_message, all_recipients)
        else:
            await asyncio.to_thread(self._send_blocking, mime_message, list(all_recipients))

    async def _send_native(self, mime_message, all_recipients: Iterable[str]) -> None:
        context = _secure_context()
        try:
            await aiosmtplib.send(
                mime_message,
                hostname=self.config.smtp_server,
                port=self.config.smtp_port,
                username=self.config.smtp_username,
                password=self.config.smtp_password,
                use_tls=self.config.smtp_ssl,
                tls_context=context,
                timeout=self.timeout,
            )
        except aiosmtplib.SMTPAuthenticationError as exc:
            raise SMTPAuthenticationError("SMTP authentication failed", cause=exc) from exc
        except aiosmtplib.SMTPRecipientsRefused as exc:
            raise RecipientRefusedError(
                "One or more recipients were refused by the server", cause=exc,
                context={"recipients": list(all_recipients)},
            ) from exc
        except aiosmtplib.SMTPConnectError as exc:
            raise SMTPConnectionError("Failed to connect to SMTP server", cause=exc) from exc
        except aiosmtplib.SMTPException as exc:
            raise SMTPSendError("SMTP transport error while sending message", cause=exc) from exc

    def _send_blocking(self, mime_message, all_recipients: list) -> None:
        context = _secure_context()
        server: Optional[smtplib.SMTP] = None
        try:
            if self.config.smtp_ssl:
                server = smtplib.SMTP_SSL(
                    self.config.smtp_server, self.config.smtp_port,
                    context=context, timeout=self.timeout,
                )
            else:
                server = smtplib.SMTP(
                    self.config.smtp_server, self.config.smtp_port, timeout=self.timeout
                )
                server.starttls(context=context)

            try:
                server.login(self.config.smtp_username, self.config.smtp_password)
            except smtplib.SMTPAuthenticationError as exc:
                raise SMTPAuthenticationError("SMTP authentication failed", cause=exc) from exc

            try:
                server.sendmail(
                    from_addr=mime_message["From"],
                    to_addrs=all_recipients,
                    msg=mime_message.as_string(),
                )
            except smtplib.SMTPRecipientsRefused as exc:
                raise RecipientRefusedError(
                    "One or more recipients were refused by the server", cause=exc,
                    context={"recipients": all_recipients},
                ) from exc
            except smtplib.SMTPException as exc:
                raise SMTPSendError("SMTP transport error while sending message", cause=exc) from exc
        except (OSError, ssl.SSLError) as exc:
            raise SMTPConnectionError("Failed to connect to SMTP server", cause=exc) from exc
        finally:
            if server is not None:
                try:
                    server.quit()
                except Exception:
                    pass
