"""Domain models for tracking replies to job applications, by email.
No infrastructure dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ReplyCategory(StrEnum):
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    INFO_REQUEST = "info_request"
    AUTO_CONFIRMATION = "auto_confirmation"
    NOISE = "noise"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class EmailReply:
    """A single email, as the mail source returns it, already normalised."""

    message_id: str
    thread_id: str
    sender: str
    subject: str
    snippet: str
    body: str
    received_at: datetime

    @property
    def searchable_text(self) -> str:
        return f"{self.subject} {self.snippet} {self.body}".lower()


@dataclass(frozen=True, slots=True)
class ClassifiedReply:
    """The result of classifying one reply."""

    reply: EmailReply
    category: ReplyCategory
    matched_keywords: tuple[str, ...] = ()
    company_guess: str = ""

    @property
    def needs_action(self) -> bool:
        """Whether this is worth a Telegram alert, as opposed to noise."""
        return self.category not in (ReplyCategory.NOISE, ReplyCategory.AUTO_CONFIRMATION)
