"""
services.attachment_handler
=============================
Validates and packages file attachments for outbound email, enforcing
size limits, an allow-list of MIME types, and security headers that
discourage automatic execution by mail clients.
"""

from __future__ import annotations

import asyncio
import mimetypes
from email import encoders
from email.mime.base import MIMEBase
from pathlib import Path
from typing import AsyncGenerator, Dict, Iterable, List

from core.exceptions import (
    AttachmentNotFoundError,
    AttachmentTooLargeError,
    UnsupportedAttachmentTypeError,
)
from core.logger import get_logger

logger = get_logger()

MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024  # 25 MB

ALLOWED_MIME_TYPES: Dict[str, str] = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "txt": "text/plain",
    "csv": "text/csv",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "zip": "application/zip",
}


class AttachmentHandler:
    """Stateless helpers for validating and building MIME attachment parts."""

    @staticmethod
    def _check_sync(file_path: str) -> Path:
        path = Path(file_path)
        if not path.is_file():
            raise AttachmentNotFoundError(
                f"Attachment file not found: {file_path}", context={"path": file_path}
            )

        size = path.stat().st_size
        if size > MAX_ATTACHMENT_SIZE:
            raise AttachmentTooLargeError(
                f"Attachment exceeds {MAX_ATTACHMENT_SIZE} bytes: {size} bytes",
                context={"path": file_path, "size": size, "limit": MAX_ATTACHMENT_SIZE},
            )

        ext = path.suffix.lstrip(".").lower()
        if ext not in ALLOWED_MIME_TYPES:
            raise UnsupportedAttachmentTypeError(
                f"Unsupported attachment type: .{ext}",
                context={"path": file_path, "extension": ext},
            )
        return path

    @classmethod
    async def validate(cls, file_path: str) -> Path:
        """Validate a single attachment off the event loop thread."""
        return await asyncio.to_thread(cls._check_sync, file_path)

    @classmethod
    async def validate_batch(
        cls, file_paths: Iterable[str]
    ) -> AsyncGenerator[tuple, None]:
        """Yield ``(path, ok, error_message)`` for each attachment."""
        for file_path in file_paths:
            try:
                await cls.validate(file_path)
                yield file_path, True, ""
            except (AttachmentNotFoundError, AttachmentTooLargeError, UnsupportedAttachmentTypeError) as exc:
                logger.warning(str(exc), extra={"error_code": exc.code, "context": exc.context})
                yield file_path, False, exc.message

    @classmethod
    async def build_part(cls, file_path: str) -> MIMEBase:
        """Validate then build a MIME part with anti-execution headers."""
        path = await cls.validate(file_path)
        ext = path.suffix.lstrip(".").lower()
        mime_type = ALLOWED_MIME_TYPES.get(ext) or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        maintype, _, subtype = mime_type.partition("/")

        data = await asyncio.to_thread(path.read_bytes)
        part = MIMEBase(maintype, subtype or "octet-stream")
        part.set_payload(data)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{path.name}"')
        part.add_header("X-Content-Type-Options", "nosniff")
        part.add_header("X-Download-Options", "noopen")
        return part

    @classmethod
    async def build_parts(cls, file_paths: Iterable[str]) -> List[MIMEBase]:
        """Build MIME parts for every attachment concurrently."""
        tasks = [cls.build_part(fp) for fp in file_paths]
        return await asyncio.gather(*tasks)
