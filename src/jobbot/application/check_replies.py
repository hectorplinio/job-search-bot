"""The reply-tracking use case: search the mailbox, classify, deduplicate,
persist and alert. Mirrors search_public_jobs.py's shape; no LLM here either
- a rejection email says what it says, there is no nuance worth paying a
model for (see reply_classification.py for why).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..domain.reply_classification import build_search_query, classify
from ..domain.reply_models import ClassifiedReply

logger = logging.getLogger(__name__)


@dataclass
class CheckRepliesReport:
    fetched: int = 0
    duplicates: int = 0
    noise: int = 0
    auto_confirmation: int = 0
    notified: int = 0
    per_category: dict[str, int] = field(default_factory=dict)
    alerts: list[ClassifiedReply] = field(default_factory=list)

    def as_text(self) -> str:
        breakdown = ", ".join(
            f"{name} {count}" for name, count in sorted(self.per_category.items())
        )
        return (
            f"📧 {self.fetched} correos revisados ({breakdown or 'ninguno'})\n"
            f"🔁 {self.duplicates} ya vistos\n"
            f"📬 {self.notified} incluidos en el aviso"
        )


class CheckReplies:
    def __init__(self, *, source, repository, notifier, days_back: int) -> None:
        self._source = source
        self._repository = repository
        self._notifier = notifier
        self._days_back = days_back

    async def run(self, *, dry_run: bool = False) -> CheckRepliesReport:
        report = CheckRepliesReport()

        query = build_search_query(self._days_back)
        replies = await self._source.search(query, max_results=100)
        report.fetched = len(replies)

        fresh = [r for r in replies if not self._repository.is_known(r.message_id)]
        report.duplicates = report.fetched - len(fresh)

        classified = [classify(reply) for reply in fresh]
        for item in classified:
            report.per_category[item.category.value] = (
                report.per_category.get(item.category.value, 0) + 1
            )

        if dry_run:
            logger.info(
                "dry-run: %s correos nuevos, %s de ellos mereceria la pena notificar "
                "(mailbox intacto)",
                len(classified),
                sum(1 for c in classified if c.needs_action),
            )
            return report

        for item in classified:
            self._repository.remember(item, notified=False)

        to_notify = [c for c in classified if c.needs_action]
        if to_notify:
            # One message for the whole batch - see format_replies_digest()
            # for why: a 64-reply run used to mean 64 separate notifications.
            await self._notifier.send_replies_digest(to_notify)
            for item in to_notify:
                self._repository.mark_notified(item.reply.message_id)
            report.notified = len(to_notify)

        report.alerts = to_notify
        return report
