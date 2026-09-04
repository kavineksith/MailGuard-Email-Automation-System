"""
models.message
===============
``EmailMessage`` is the core value object passed between the validator,
attachment handler, template engine, and SMTP client. It implements a
full dunder-method suite so instances behave predictably in collections,
comparisons, and debugging sessions.
"""

from __future__ import annotations

import enum
import pickle
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional
from uuid import uuid4


class MessageStatus(enum.Enum):
    """Lifecycle state of an :class:`EmailMessage`."""

    PENDING = "PENDING"
    QUEUED = "QUEUED"
    SENDING = "SENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    def __str__(self) -> str:
        return self.value


# Module-level ordering so terminal states (SENT/FAILED/CANCELLED) never
# get shadowed by member definitions inside the enum class body, and so
# `is not None` (not truthiness) is what callers use to test "unset".
_STATUS_ORDER: Dict[MessageStatus, int] = {
    MessageStatus.PENDING: 0,
    MessageStatus.QUEUED: 1,
    MessageStatus.SENDING: 2,
    MessageStatus.SENT: 3,
    MessageStatus.FAILED: 3,
    MessageStatus.CANCELLED: 3,
}


@dataclass
class EmailMessage:
    """A single outbound email, independent of transport concerns."""

    subject: str
    body: str
    recipients: List[str]
    sender: str
    cc: List[str] = field(default_factory=list)
    bcc: List[str] = field(default_factory=list)
    attachments: List[str] = field(default_factory=list)
    template_name: Optional[str] = None
    template_context: Dict[str, Any] = field(default_factory=dict)
    is_html: bool = False
    message_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: MessageStatus = MessageStatus.PENDING
    scheduled_time: Optional[str] = None

    # -- container protocol --------------------------------------------------

    def __iter__(self) -> Iterator[str]:
        """Iterate over all resolved recipients (to + cc + bcc)."""
        return iter(self.all_recipients())

    def __len__(self) -> int:
        return len(self.all_recipients())

    def __contains__(self, address: object) -> bool:
        return address in self.all_recipients()

    def __getitem__(self, index: int) -> str:
        return self.all_recipients()[index]

    def __bool__(self) -> bool:
        """A message is truthy only if it has a subject and a recipient."""
        return bool(self.subject) and bool(self.recipients)

    # -- comparison / hashing -------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EmailMessage):
            return NotImplemented
        return self.message_id == other.message_id

    def __hash__(self) -> int:
        return hash(self.message_id)

    def __lt__(self, other: "EmailMessage") -> bool:
        if not isinstance(other, EmailMessage):
            return NotImplemented
        return self.created_at < other.created_at

    # -- representation ---------------------------------------------------

    def __str__(self) -> str:
        return f"EmailMessage(id={self.message_id[:8]}, subject={self.subject!r}, status={self.status})"

    def __repr__(self) -> str:
        return (
            f"EmailMessage(message_id={self.message_id!r}, subject={self.subject!r}, "
            f"recipients={self.recipients!r}, status={self.status!r})"
        )

    # -- pickle support -----------------------------------------------------

    def __getstate__(self) -> Dict[str, Any]:
        state = self.__dict__.copy()
        state["status"] = self.status.value
        return state

    def __setstate__(self, state: Dict[str, Any]) -> None:
        state["status"] = MessageStatus(state["status"])
        self.__dict__.update(state)

    # -- helpers -----------------------------------------------------------

    def all_recipients(self) -> List[str]:
        return [*self.recipients, *self.cc, *self.bcc]

    def is_terminal(self) -> bool:
        return _STATUS_ORDER.get(self.status, 0) == 3

    def mark(self, status: MessageStatus) -> None:
        self.status = status

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "subject": self.subject,
            "recipients": self.recipients,
            "cc": self.cc,
            "bcc": self.bcc,
            "sender": self.sender,
            "attachments": self.attachments,
            "status": str(self.status),
            "created_at": self.created_at.isoformat(),
            "scheduled_time": self.scheduled_time,
        }

    def clone_for_retry(self) -> "EmailMessage":
        """Return a fresh copy suitable for re-queueing after a failure."""
        clone = pickle.loads(pickle.dumps(self))
        clone.message_id = str(uuid4())
        clone.status = MessageStatus.PENDING
        return clone
