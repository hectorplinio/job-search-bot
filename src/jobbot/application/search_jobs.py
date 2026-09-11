"""Caso de uso principal: buscar, filtrar, deduplicar, puntuar y avisar."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from ..domain.criteria import Criteria
from ..domain.fingerprint import fingerprint as compute_fingerprint
from ..domain.fingerprint import url_key as compute_url_key
from ..domain.models import JobOffer, ScoredOffer
from ..domain.profile import CandidateProfile
from ..domain.scoring import score_offer

logger = logging.getLogger(__name__)


@dataclass
class SearchReport:
    """Lo que paso en una ejecucion. Se imprime en consola y en Telegram."""

    fetched: int = 0
    duplicates: int = 0
    rejected: int = 0
    below_threshold: int = 0
    notified: int = 0
    llm_calls: int = 0
    per_source: dict[str, int] = field(default_factory=dict)
    alerts: list[ScoredOffer] = field(default_factory=list)

    def as_text(self) -> str:
        sources = ", ".join(f"{name} {count}" for name, count in sorted(self.per_source.items()))
        return "\n".join(
            [
                f"📊 {self.fetched} ofertas revisadas ({sources or 'sin fuentes'})",
                f"🔁 {self.duplicates} repetidas · 🚫 {self.rejected} descartadas por filtros",
                f"📉 {self.below_threshold} por debajo del umbral",
                f"📬 {self.notified} enviadas",
            ]
        )


class SearchJobs:
    """Orquesta fuentes, historial, scoring y notificacion.

    El orden importa: primero los filtros baratos (reglas), luego el historial,
    y solo al final el LLM, que es lo unico que cuesta dinero.
    """

    def __init__(
        self,
        *,
        sources: list,
        repository,
        notifier,
        criteria: Criteria,
        profile: CandidateProfile,
        writer=None,
    ) -> None:
        self._sources = sources
        self._repository = repository
        self._notifier = notifier
        self._criteria = criteria
        self._profile = profile
        self._writer = writer
        # El url_key no vive en ScoredOffer porque solo lo necesita el
        # repositorio; se guarda aparte, indexado por huella.
        self._url_keys: dict[str, str] = {}

    async def run(self, *, dry_run: bool = False) -> SearchReport:
        report = SearchReport()

        harvested = await self._harvest(report)
        fresh = self._drop_known(harvested, report)
        candidates = self._score(fresh, report, persist=not dry_run)
        candidates = await self._refine_with_llm(candidates, report)

        threshold = self._criteria.scoring.notify_threshold
        passing = [item for item in candidates if item.score.value >= threshold]
        report.below_threshold = len(candidates) - len(passing)

        passing.sort(key=lambda item: item.score.value, reverse=True)
        alerts = passing[: self._criteria.telegram.max_alerts_per_run]
        report.alerts = alerts

        await self._persist_and_notify(candidates, alerts, report, dry_run=dry_run)
        return report

    async def _harvest(self, report: SearchReport) -> list[JobOffer]:
        results = await asyncio.gather(
            *(source.safe_search(self._criteria) for source in self._sources)
        )
        harvested: list[JobOffer] = []
        for source, offers in zip(self._sources, results, strict=True):
            report.per_source[source.name] = len(offers)
            harvested.extend(offers)
        report.fetched = len(harvested)
        return harvested

    def _drop_known(self, offers: list[JobOffer], report: SearchReport) -> list[tuple]:
        """Quita lo que ya esta en el historial y lo repetido dentro del lote."""
        seen_in_batch: set[str] = set()
        fresh: list[tuple[JobOffer, str, str]] = []

        for offer in offers:
            fingerprint = compute_fingerprint(offer)
            url_key = compute_url_key(offer.url)
            if fingerprint in seen_in_batch:
                report.duplicates += 1
                continue
            if self._repository.is_known(fingerprint, url_key):
                report.duplicates += 1
                continue
            seen_in_batch.add(fingerprint)
            fresh.append((offer, fingerprint, url_key))

        return fresh

    def _score(
        self, fresh: list[tuple], report: SearchReport, *, persist: bool
    ) -> list[ScoredOffer]:
        scored: list[ScoredOffer] = []
        for offer, fingerprint, url_key in fresh:
            score = score_offer(offer, self._criteria)
            item = ScoredOffer(offer=offer, score=score, fingerprint=fingerprint)
            self._url_keys[fingerprint] = url_key
            if score.is_rejected:
                report.rejected += 1
                if persist:
                    self._repository.remember(item, notified=False, url_key=url_key)
                continue
            scored.append(item)
        return scored

    async def _refine_with_llm(
        self, candidates: list[ScoredOffer], report: SearchReport
    ) -> list[ScoredOffer]:
        scoring = self._criteria.scoring
        if self._writer is None or not scoring.use_llm or not candidates:
            return candidates

        eligible = [item for item in candidates if item.score.value >= scoring.llm_min_rule_score]
        eligible.sort(key=lambda item: item.score.value, reverse=True)
        eligible = eligible[: scoring.llm_max_offers_per_run]
        if not eligible:
            return candidates

        verdicts = await self._writer.rate(
            [(item.offer, item.score) for item in eligible],
            self._profile,
            salary_minimum=self._criteria.salary.minimum,
            salary_target=self._criteria.salary.target,
        )
        report.llm_calls = len(eligible)

        refined = {
            item.fingerprint: ScoredOffer(
                offer=item.offer,
                score=score,
                fingerprint=item.fingerprint,
                summary=summary,
            )
            for item, (score, summary) in zip(eligible, verdicts, strict=False)
        }
        return [refined.get(item.fingerprint, item) for item in candidates]

    async def _persist_and_notify(
        self,
        candidates: list[ScoredOffer],
        alerts: list[ScoredOffer],
        report: SearchReport,
        *,
        dry_run: bool,
    ) -> None:
        if dry_run:
            # Un ensayo no puede dejar rastro: si guardase, la siguiente
            # ejecucion de verdad daria estas ofertas por vistas y no te
            # llegaria ninguna.
            logger.info("dry-run: %s ofertas se habrian enviado (historial intacto)", len(alerts))
            return

        alert_ids = {item.fingerprint for item in alerts}
        for item in candidates:
            self._repository.remember(
                item,
                notified=item.fingerprint in alert_ids,
                url_key=self._url_keys.get(item.fingerprint, item.fingerprint),
            )

        for item in alerts:
            await self._notifier.send_offer(item)
            report.notified += 1
