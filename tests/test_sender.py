from unittest.mock import AsyncMock, patch

import pytest

from core.config import ConfigManager
from core.exceptions import InvalidEmailError
from models.message import EmailMessage, MessageStatus
from services.sender import EmailSender

VALID_DATA = {
    "smtp_server": "smtp.example.com",
    "smtp_port": 587,
    "smtp_username": "user",
    "smtp_password": "secret",
    "default_sender": "noreply@example.com",
}


async def _make_sender(tmp_path):
    manager = ConfigManager(str(tmp_path / "c.enc"), str(tmp_path / "s"))
    await manager.save(VALID_DATA)
    sender = EmailSender(manager)
    await sender.initialize()
    return sender


@pytest.mark.asyncio
async def test_send_success_marks_sent(tmp_path):
    sender = await _make_sender(tmp_path)
    with patch.object(sender._client, "send", new=AsyncMock(return_value=None)):
        message = EmailMessage(
            subject="Hi", body="Body", recipients=["a@example.com"], sender="noreply@example.com"
        )
        result = await sender.send(message)
        assert result.status == MessageStatus.SENT


@pytest.mark.asyncio
async def test_send_invalid_recipient_marks_failed(tmp_path):
    sender = await _make_sender(tmp_path)
    message = EmailMessage(
        subject="Hi", body="Body", recipients=["not-an-email"], sender="noreply@example.com"
    )
    with pytest.raises(InvalidEmailError):
        await sender.send(message)
    assert message.status == MessageStatus.FAILED


@pytest.mark.asyncio
async def test_send_bulk_tolerates_partial_failure(tmp_path):
    sender = await _make_sender(tmp_path)
    with patch.object(sender._client, "send", new=AsyncMock(return_value=None)):
        good = EmailMessage(subject="Hi", body="B", recipients=["a@example.com"], sender="noreply@example.com")
        bad = EmailMessage(subject="Hi", body="B", recipients=["bad"], sender="noreply@example.com")
        results = await sender.send_bulk([good, bad])
        statuses = {r.message_id: r.status for r in results}
        assert statuses[good.message_id] == MessageStatus.SENT
        assert statuses[bad.message_id] == MessageStatus.FAILED


@pytest.mark.asyncio
async def test_send_bulk_runs_concurrently(tmp_path):
    sender = await _make_sender(tmp_path)
    with patch.object(sender._client, "send", new=AsyncMock(return_value=None)) as mock_send:
        messages = [
            EmailMessage(subject="Hi", body="B", recipients=["a@example.com"], sender="noreply@example.com")
            for _ in range(5)
        ]
        results = await sender.send_bulk(messages)
        assert len(results) == 5
        assert mock_send.await_count == 5
