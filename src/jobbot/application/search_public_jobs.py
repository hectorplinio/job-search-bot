"""The public-sector use case: search, filter, deduplicate, score and alert.

Deliberately simpler than SearchJobs: no LLM refinement (a vacancy either
matches the TIC keywords and your scope or it does not - there is no
"nuance" worth paying a model for), and urgency overrides the score
threshold instead of sorting against it.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field

from ..domain.criteria import PublicCriteria
from ..domain.public_models import Oposicion, ScoredOposicion
from ..domain.public_scoring import score_oposicion

logger = logging.getLogger(__name__)


def oposicion_fingerprint(oposicion: Oposicion) -> str:
    """The official identifier is already a stable, unique key - no fuzzy
    matching needed, unlike private postings that show up on five boards
    under five slightly different titles."""
    key = f"{oposicion.fuente}:{oposicion.identificador}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()  # noqa: S324 - not cryptography


@dataclass
class PublicSearchReport:
    fetched: int = 0
    duplicates: int = 0
    rejected: int = 0
    below_threshold: int = 0
    notified: int = 0
    urgent: int = 0
    per_source: dict[str, int] = field(default_factory=dict)
    alerts: list[ScoredOposicion] = field(default_factory=list)

    def as_text(self) -> str:
        sources = ", ".join(f"{name} {count}" for name, count in sorted(self.per_source.items()))
        urgentes = f" (🚨 {self.urgent} urgentes)" if self.urgent else ""
        lines = [
            f"🏛️ {self.fetched} oposiciones revisadas ({sources or 'sin fuentes'})",
            f"🔁 {self.duplicates} repetidas · 🚫 {self.rejected} descartadas por filtros",
            f"📬 {self.notified} enviadas{urgentes}",
        ]
        return "\n".join(lines)


class SearchPublicJobs:
    def __init__(
        self,
        *,
        sources: list,
        repository,
        notifier,
        criteria: PublicCriteria,
    ) -> None:
        self._sources = sources
        self._repository = repository
        self._notifier = notifier
        self._criteria = criteria

    async def run(self, *, dry_run: bool = False) -> PublicSearchReport:
        report = PublicSearchReport()
        if not self._criteria.enabled or not self._sources:
            return report

        harvested = await self._harvest(report)
        fresh = self._drop_known(harvested, report)
        candidates = self._score(fresh, report, persist=not dry_run)

        if dry_run:
            logger.info(
                "dry-run: %s oposiciones would have been sent (history untouched)",
                len(candidates),
            )
            return report

        await self._notify(candidates, report)
        return report

    async def _harvest(self, report: PublicSearchReport) -> list[Oposicion]:
        results = await asyncio.gather(
            *(source.safe_search(self._criteria) for source in self._sources)
        )
        harvested: list[Oposicion] = []
        for source, items in zip(self._sources, results, strict=True):
            report.per_source[source.name] = len(items)
            harvested.extend(items)
        report.fetched = len(harvested)
        return harvested

    def _drop_known(
        self, items: list[Oposicion], report: PublicSearchReport
    ) -> list[tuple[Oposicion, str]]:
        seen_in_batch: set[str] = set()
        fresh: list[tuple[Oposicion, str]] = []
        for oposicion in items:
            fingerprint = oposicion_fingerprint(oposicion)
            if fingerprint in seen_in_batch or self._repository.is_known(fingerprint):
                report.duplicates += 1
                continue
            seen_in_batch.add(fingerprint)
            fresh.append((oposicion, fingerprint))
        return fresh

    def _score(
        self, fresh: list[tuple[Oposicion, str]], report: PublicSearchReport, *, persist: bool
    ) -> list[ScoredOposicion]:
        scored: list[ScoredOposicion] = []
        for oposicion, fingerprint in fresh:
            score = score_oposicion(oposicion, self._criteria)
            item = ScoredOposicion(oposicion=oposicion, score=score, fingerprint=fingerprint)
            if score.is_rejected:
                report.rejected += 1
                if persist:
                    self._repository.remember(item, notified=False)
                continue
            scored.append(item)
        return scored

    async def _notify(self, candidates: list[ScoredOposicion], report: PublicSearchReport) -> None:
        for item in candidates:
            self._repository.remember(item, notified=False)

        # Urgent ones ignore the score threshold entirely: a 10-business-day
        # window in your own town is worth more than the score says.
        passing = [
            item
            for item in candidates
            if item.score.urgent or item.score.value >= self._criteria.notify_threshold
        ]
        report.below_threshold = len(candidates) - len(passing)

        to_send = self._repository.top_pending(limit=50, min_score=self._criteria.notify_threshold)
        for item in to_send:
            await self._notifier.send_oposicion(item)
            self._repository.mark_notified(item.fingerprint)
            report.notified += 1
            if item.score.urgent:
                report.urgent += 1

        report.alerts = to_send
