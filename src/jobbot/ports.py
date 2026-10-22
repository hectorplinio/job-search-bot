"""Ports: what the domain needs from outside, without knowing who provides it."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .domain.criteria import Criteria, PublicCriteria
from .domain.models import ApplicationDocuments, JobOffer, MatchScore, ScoredOffer
from .domain.profile import CandidateProfile
from .domain.public_models import Oposicion, ScoredOposicion
from .domain.reply_models import ClassifiedReply, EmailReply


@runtime_checkable
class JobSource(Protocol):
    """A source of job postings (LinkedIn, Manfred, InfoJobs...)."""

    name: str

    async def search(self, criteria: Criteria) -> list[JobOffer]:
        """Returns normalised postings. Never raises: on failure it returns []."""
        ...


@runtime_checkable
class OfferReader(Protocol):
    """Reads a single posting from its URL (manual mode)."""

    async def read(self, url: str) -> JobOffer: ...


@runtime_checkable
class OfferRepository(Protocol):
    """The history of postings already processed."""

    def is_known(self, fingerprint: str, url_key: str) -> bool: ...

    def remember(self, scored: ScoredOffer, *, notified: bool) -> None: ...

    def top_pending(self, limit: int) -> list[ScoredOffer]: ...

    def stats(self) -> dict[str, int]: ...

    def mark_notified(self, fingerprint: str) -> None: ...


@runtime_checkable
class Notifier(Protocol):
    """The way out to the user (Telegram)."""

    async def send_offer(self, scored: ScoredOffer) -> None: ...

    async def send_text(self, text: str) -> None: ...


@runtime_checkable
class PublicSource(Protocol):
    """A source of public-sector postings (BOE, BOPA, DOGV, BORM...)."""

    name: str

    async def search(self, criteria: PublicCriteria, *, on: object = None) -> list[Oposicion]:
        """Returns normalised vacancies for a given day. Never raises: on
        failure it returns []. `on` lets callers ask for a specific date
        (tests, backfills); the default is "today"."""
        ...


@runtime_checkable
class PublicOfferRepository(Protocol):
    """The history of oposiciones already processed."""

    def is_known(self, fingerprint: str) -> bool: ...

    def remember(self, scored: ScoredOposicion, *, notified: bool) -> None: ...

    def top_pending(self, limit: int) -> list[ScoredOposicion]: ...

    def mark_notified(self, fingerprint: str) -> None: ...


@runtime_checkable
class EmailSource(Protocol):
    """Read-only access to a mailbox (Gmail...). Never sends, never deletes."""

    async def search(self, query: str, *, max_results: int = 50) -> list[EmailReply]:
        """Messages matching `query`, newest first. Never raises: on failure
        it returns []."""
        ...


@runtime_checkable
class ReplyRepository(Protocol):
    """The history of replies already classified."""

    def is_known(self, message_id: str) -> bool: ...

    def remember(self, classified: ClassifiedReply, *, notified: bool) -> None: ...

    def pending(self, limit: int) -> list[ClassifiedReply]: ...

    def mark_notified(self, message_id: str) -> None: ...

    def all(self) -> list[ClassifiedReply]:
        """Every reply ever seen, oldest first - the raw material for a
        per-thread recap. Unbounded on purpose: a few hundred rows of text
        is nothing to hold in memory, and a hidden limit here would just
        mean a recap that silently drops old threads."""
        ...


@runtime_checkable
class DocumentWriter(Protocol):
    """Assisted writing: cover letter, summary and a second opinion on scoring."""

    async def rate(
        self, offer: JobOffer, profile: CandidateProfile, rule_score: MatchScore
    ) -> MatchScore: ...

    async def write(self, offer: JobOffer, profile: CandidateProfile) -> ApplicationDocuments: ...
