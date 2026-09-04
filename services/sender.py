"""
services.sender
==================
Orchestrates validation, template rendering, attachment packaging, and
delivery. Bulk sends are bounded by an ``asyncio.Semaphore`` and driven
through ``asyncio.gather`` so many messages can be in flight at once
without overwhelming the SMTP server or the local machine.
"""

from __future__ import annotations

import asyncio
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Iterable, List

from core.config import ConfigManager
from core.exceptions import MailGuardError, TemplateRenderError
from core.logger import get_logger, log_exception
from models.message import EmailMessage, MessageStatus
from services.attachment_handler import AttachmentHandler
from services.smtp_client import AsyncSMTPClient
from services.template_engine import TemplateEngine
from validators.email_validator import EmailValidator

logger = get_logger()


class EmailSender:
    """High-level façade used by the CLI and scheduler."""

    def __init__(self, config_manager: ConfigManager, max_concurrency: int = 5) -> None:
        self.config_manager = config_manager
        self.template_engine = TemplateEngine()
        self._client: AsyncSMTPClient | None = None
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def initialize(self) -> None:
        """Load configuration and prepare the SMTP client. Call once at startup."""
        config = await self.config_manager.load()
        self._client = AsyncSMTPClient(config)
        self._semaphore = asyncio.Semaphore(max(1, config.max_concurrent_sends))
        logger.info("EmailSender initialized")

    def __repr__(self) -> str:
        return f"EmailSender(client={self._client!r})"

    async def _build_mime(self, message: EmailMessage) -> MIMEMultipart:
        mime = MIMEMultipart()
        mime["From"] = message.sender
        mime["To"] = ", ".join(message.recipients)
        mime["Subject"] = message.subject
        if message.cc:
            mime["Cc"] = ", ".join(message.cc)

        if message.template_name:
            try:
                body = await self.template_engine.render(message.template_name, message.template_context)
            except MailGuardError:
                raise
            except Exception as exc:  # defensive: template engine internals
                raise TemplateRenderError("Unexpected template rendering failure", cause=exc) from exc
            mime.attach(MIMEText(body, "html"))
        else:
            mime.attach(MIMEText(message.body, "html" if message.is_html else "plain"))

        if message.attachments:
            parts = await AttachmentHandler.build_parts(message.attachments)
            for part in parts:
                mime.attach(part)

        return mime

    async def send(self, message: EmailMessage) -> EmailMessage:
        """Validate, render, and deliver a single message."""
        async with self._semaphore:
            message.mark(MessageStatus.SENDING)
            try:
                await EmailValidator.validate_all(message.all_recipients())
                EmailValidator.validate(message.sender)

                mime = await self._build_mime(message)
                assert self._client is not None, "call initialize() before send()"
                await self._client.send(mime, message.all_recipients())

                message.mark(MessageStatus.SENT)
                logger.info(
                    f"Message {message.message_id} delivered to {len(message.recipients)} recipient(s)",
                    extra={"context": message.to_dict()},
                )
            except MailGuardError as exc:
                message.mark(MessageStatus.FAILED)
                log_exception(logger, exc)
                raise
            return message

    async def send_bulk(self, messages: Iterable[EmailMessage]) -> List[EmailMessage]:
        """
        Send many messages concurrently (bounded by the configured
        semaphore), tolerating individual failures.
        """
        results = await asyncio.gather(
            *(self._send_tolerant(m) for m in messages), return_exceptions=False
        )
        return list(results)

    async def _send_tolerant(self, message: EmailMessage) -> EmailMessage:
        try:
            return await self.send(message)
        except MailGuardError:
            return message  # already marked FAILED and logged
