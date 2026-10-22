"""One row per conversation, not per email - the status view of the whole
mailbox history instead of a firehose of individual messages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .reply_models import ClassifiedReply, ReplyCategory


def _contact_name(sender: str) -> str:
    if "<" in sender:
        name = sender.split("<", 1)[0].strip().strip('"')
        return name or sender
    return sender


@dataclass(frozen=True, slots=True)
class ThreadStatus:
    company: str
    contact: str
    category: ReplyCategory
    subject: str
    last_update: datetime


def build_recap(replies: list[ClassifiedReply]) -> list[ThreadStatus]:
    """One ThreadStatus per thread_id, newest first: the company comes from
    the thread's first message (a thread almost never opens with your own
    outgoing mail, so that is reliably the recruiter/platform/ATS), and the
    status comes from its most recent one - which is often you, following
    up, and that is still the right answer to "what's the last thing that
    happened here"."""
    by_thread: dict[str, list[ClassifiedReply]] = {}
    for item in sorted(replies, key=lambda c: c.reply.received_at):
        by_thread.setdefault(item.reply.thread_id, []).append(item)

    statuses: list[ThreadStatus] = []
    for items in by_thread.values():
        if all(item.category == ReplyCategory.NOISE for item in items):
            continue
        first, last = items[0], items[-1]
        statuses.append(
            ThreadStatus(
                company=first.company_guess or "?",
                contact=_contact_name(last.reply.sender),
                category=last.category,
                subject=last.reply.subject or "(sin asunto)",
                last_update=last.reply.received_at,
            )
        )

    return sorted(statuses, key=lambda s: s.last_update, reverse=True)
