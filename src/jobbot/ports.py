"""Puertos: lo que el dominio necesita del exterior, sin saber quien lo cumple."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .domain.criteria import Criteria
from .domain.models import ApplicationDocuments, JobOffer, MatchScore, ScoredOffer
from .domain.profile import CandidateProfile


@runtime_checkable
class JobSource(Protocol):
    """Una fuente de ofertas (LinkedIn, Manfred, InfoJobs...)."""

    name: str

    async def search(self, criteria: Criteria) -> list[JobOffer]:
        """Devuelve ofertas ya normalizadas. Nunca lanza: si falla, devuelve []."""
        ...


@runtime_checkable
class OfferReader(Protocol):
    """Lee una oferta suelta a partir de su URL (modo manual)."""

    async def read(self, url: str) -> JobOffer: ...


@runtime_checkable
class OfferRepository(Protocol):
    """Historial de ofertas ya procesadas."""

    def is_known(self, fingerprint: str, url_key: str) -> bool: ...

    def remember(self, scored: ScoredOffer, *, notified: bool) -> None: ...

    def top_pending(self, limit: int) -> list[ScoredOffer]: ...

    def stats(self) -> dict[str, int]: ...

    def mark_notified(self, fingerprint: str) -> None: ...


@runtime_checkable
class Notifier(Protocol):
    """Salida hacia el usuario (Telegram)."""

    async def send_offer(self, scored: ScoredOffer) -> None: ...

    async def send_text(self, text: str) -> None: ...


@runtime_checkable
class DocumentWriter(Protocol):
    """Redaccion asistida: cover letter, summary y segunda opinion del scoring."""

    async def rate(
        self, offer: JobOffer, profile: CandidateProfile, rule_score: MatchScore
    ) -> MatchScore: ...

    async def write(self, offer: JobOffer, profile: CandidateProfile) -> ApplicationDocuments: ...
