import asyncio
from unittest.mock import AsyncMock

import pytest

from core.exceptions import InvalidScheduleTimeError, JobAlreadyExistsError, JobNotFoundError
from models.message import EmailMessage
from services.scheduler import EmailScheduler


def make_message():
    return EmailMessage(subject="s", body="b", recipients=["a@example.com"], sender="me@example.com")


@pytest.mark.asyncio
async def test_invalid_schedule_time_raises():
    sender = AsyncMock()
    scheduler = EmailScheduler(sender)
    with pytest.raises(InvalidScheduleTimeError):
        await scheduler.schedule(make_message(), "25:99")


@pytest.mark.asyncio
async def test_duplicate_job_id_raises():
    sender = AsyncMock()
    scheduler = EmailScheduler(sender)
    job_id = "job-1"
    await scheduler.schedule(make_message(), "23:59", job_id=job_id)
    with pytest.raises(JobAlreadyExistsError):
        await scheduler.schedule(make_message(), "23:59", job_id=job_id)
    await scheduler.cancel(job_id)


@pytest.mark.asyncio
async def test_cancel_unknown_job_raises():
    sender = AsyncMock()
    scheduler = EmailScheduler(sender)
    with pytest.raises(JobNotFoundError):
        await scheduler.cancel("does-not-exist")


@pytest.mark.asyncio
async def test_cancel_removes_pending_job():
    sender = AsyncMock()
    scheduler = EmailScheduler(sender)
    job_id = await scheduler.schedule(make_message(), "23:58")
    assert job_id in scheduler
    await scheduler.cancel(job_id)
    assert job_id not in scheduler


@pytest.mark.asyncio
async def test_len_reflects_pending_jobs():
    sender = AsyncMock()
    scheduler = EmailScheduler(sender)
    await scheduler.schedule(make_message(), "23:57")
    assert len(scheduler) == 1
