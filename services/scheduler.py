"""
services.scheduler
=====================
A lightweight async scheduler that owns a single background task per
job. Jobs are keyed by ``job_id`` so duplicates are rejected and
in-flight jobs can be cancelled cleanly.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional
from uuid import uuid4

from core.exceptions import InvalidScheduleTimeError, JobAlreadyExistsError, JobNotFoundError
from core.logger import get_logger
from models.message import EmailMessage
from services.sender import EmailSender

logger = get_logger()


@dataclass
class ScheduledJob:
    job_id: str
    message: EmailMessage
    run_at: datetime
    task: Optional[asyncio.Task] = None

    def __repr__(self) -> str:
        return f"ScheduledJob(job_id={self.job_id}, run_at={self.run_at.isoformat()})"


class EmailScheduler:
    """Schedules :class:`EmailMessage` objects for future delivery."""

    def __init__(self, sender: EmailSender) -> None:
        self.sender = sender
        self._jobs: Dict[str, ScheduledJob] = {}

    def __len__(self) -> int:
        return len(self._jobs)

    def __contains__(self, job_id: object) -> bool:
        return job_id in self._jobs

    def __repr__(self) -> str:
        return f"EmailScheduler(pending_jobs={len(self)})"

    @staticmethod
    def _parse_time(schedule_time: str) -> datetime:
        try:
            hour, minute = (int(part) for part in schedule_time.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except ValueError as exc:
            raise InvalidScheduleTimeError(
                f"Invalid schedule time format, expected HH:MM: {schedule_time!r}",
                context={"schedule_time": schedule_time},
            ) from exc

        now = datetime.now()
        run_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if run_at <= now:
            run_at += timedelta(days=1)
        return run_at

    async def schedule(self, message: EmailMessage, schedule_time: str, job_id: Optional[str] = None) -> str:
        """Register a message to be sent at ``schedule_time`` (HH:MM, next occurrence)."""
        job_id = job_id or str(uuid4())
        if job_id in self._jobs:
            raise JobAlreadyExistsError(f"Job already scheduled: {job_id}", context={"job_id": job_id})

        run_at = self._parse_time(schedule_time)
        message.scheduled_time = schedule_time
        job = ScheduledJob(job_id=job_id, message=message, run_at=run_at)
        job.task = asyncio.create_task(self._run_job(job))
        self._jobs[job_id] = job
        logger.info(f"Scheduled job {job_id} for {run_at.isoformat()}", extra={"context": {"job_id": job_id}})
        return job_id

    async def _run_job(self, job: ScheduledJob) -> None:
        delay = max(0.0, (job.run_at - datetime.now()).total_seconds())
        try:
            await asyncio.sleep(delay)
            await self.sender.send(job.message)
        except asyncio.CancelledError:
            logger.info(f"Job {job.job_id} cancelled before delivery")
            raise
        finally:
            self._jobs.pop(job.job_id, None)

    async def cancel(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFoundError(f"No such scheduled job: {job_id}", context={"job_id": job_id})
        if job.task:
            job.task.cancel()
        self._jobs.pop(job_id, None)

    async def wait_all(self) -> None:
        """Block until every currently scheduled job has run or been cancelled."""
        tasks = [job.task for job in self._jobs.values() if job.task]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
