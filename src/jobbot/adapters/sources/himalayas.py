"""Himalayas.

A public JSON API, no key, aimed at remote-first companies, many of them from
the United States.

Its `locationRestrictions` field is the most precise piece of data any source
gives: an explicit list of countries they accept candidates from. Empty means
no restriction. With that you know for certain whether you can apply from
Spain, instead of inferring it from the posting text.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ...domain.criteria import Criteria
from ...domain.models import JobOffer, WorkMode
from ...domain.salary import from_bounds
from ...domain.scoring import contains_term
from .base import BaseSource, can_work_from, clean_text

logger = logging.getLogger(__name__)

API_URL = "https://himalayas.app/jobs/api"
# It serves 20 per request even if you ask for 100, but the offset does work
# and its catalogue is over 100,000 postings. Without paging you saw twenty,
# and three quarters of those were United States only.
PAGE_SIZE = 20
DEFAULT_PAGES = 6


class HimalayasSource(BaseSource):
    name = "himalayas"

    async def search(self, criteria: Criteria) -> list[JobOffer]:
        rows = await self._fetch_pages(int(self.options.get("pages", DEFAULT_PAGES)))
        if not rows:
            logger.info("Himalayas returned no postings")
            return []

        terms = criteria.keywords.required_any
        fuera_de_alcance = 0
        offers: list[JobOffer] = []

        for row in rows:
            paises = ", ".join(row.get("locationRestrictions") or [])
            if not can_work_from(paises):
                fuera_de_alcance += 1
                continue
            if not self._matches(row, terms):
                continue
            offers.append(self._to_offer(row, paises))

        if fuera_de_alcance:
            logger.info(
                "Himalayas: %s postings do not accept candidates from Spain", fuera_de_alcance
            )
        return offers[: criteria.search.max_results_per_source]

    async def _fetch_pages(self, pages: int) -> list[dict]:
        """Walks the catalogue by offset until it runs out or hits the cap."""
        recogidas: list[dict] = []
        vistos: set[str] = set()
        for numero in range(pages):
            params = {"limit": PAGE_SIZE, "offset": numero * PAGE_SIZE}
            try:
                payload = await self.http.get_json(API_URL, params=params)
            except Exception:  # noqa: BLE001 - one failed page does not void the others
                logger.debug("Himalayas failed at offset %s", numero * PAGE_SIZE)
                break

            pagina = payload.get("jobs") if isinstance(payload, dict) else None
            if not pagina:
                break
            nuevas = [row for row in pagina if row.get("guid") not in vistos]
            vistos.update(row.get("guid") for row in pagina)
            recogidas.extend(nuevas)
            # If it stops returning new postings, asking for more is pointless.
            if not nuevas:
                break
        return recogidas

    @staticmethod
    def _matches(row: dict, terms: list[str]) -> bool:
        haystack = " ".join(
            [
                row.get("title") or "",
                row.get("excerpt") or "",
                row.get("description") or "",
                *(row.get("categories") or []),
            ]
        ).lower()
        return any(contains_term(haystack, term) for term in terms)

    def _to_offer(self, row: dict, paises: str) -> JobOffer:
        posted_at = None
        raw = row.get("pubDate") or row.get("publishedDate")
        if isinstance(raw, int | float):
            # They publish it as an epoch in seconds.
            posted_at = datetime.fromtimestamp(raw, tz=UTC).date()
        elif raw:
            try:
                posted_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
            except ValueError:
                posted_at = None

        return JobOffer(
            source=self.name,
            external_id=f"himalayas:{row.get('guid')}",
            title=clean_text(row.get("title")),
            company=clean_text(row.get("companyName")),
            url=row.get("applicationLink") or "",
            description=clean_text(row.get("description") or row.get("excerpt")),
            location=paises or "Sin restriccion de pais",
            work_mode=WorkMode.REMOTE,
            salary=from_bounds(
                row.get("minSalary"), row.get("maxSalary"), row.get("currency") or "USD"
            ),
            posted_at=posted_at,
            tags=tuple(row.get("categories") or ()),
        )
