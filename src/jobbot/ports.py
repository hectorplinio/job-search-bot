"""Ports: what the domain needs from outside, without knowing who provides it."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .domain.criteria import Criteria
from .domain.models import ApplicationDocuments, JobOffer, MatchScore, ScoredOffer
from .domain.profile import CandidateProfile


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
class DocumentWriter(Protocol):
    """Assisted writing: cover letter, summary and a second opinion on scoring."""

    async def rate(
        self, offer: JobOffer, profile: CandidateProfile, rule_score: MatchScore
    ) -> MatchScore: ...

    async def write(self, offer: JobOffer, profile: CandidateProfile) -> ApplicationDocuments: ...
