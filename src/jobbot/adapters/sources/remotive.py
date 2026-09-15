"""Remotive.

A public JSON API, no key. Almost all of it is United States companies hiring
remotely, which is exactly the gap the Spanish boards leave open.

The valuable part is the `candidate_required_location` field: it says where
they accept candidates from. A remote posting that says "USA" cannot be
accepted from Spain, and with that field it is dropped before spending
anything on it.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from ...domain.criteria import Criteria
from ...domain.models import JobOffer, WorkMode
from ...domain.salary import parse_salary
from ...domain.scoring import contains_term
from .base import BaseSource, can_work_from, clean_text

logger = logging.getLogger(__name__)

API_URL = "https://remotive.com/api/remote-jobs"
DEFAULT_CATEGORY = "software-dev"


class RemotiveSource(BaseSource):
    name = "remotive"

    async def search(self, criteria: Criteria) -> list[JobOffer]:
        params = {"category": self.options.get("category", DEFAULT_CATEGORY)}
        payload = await self.http.get_json(API_URL, params=params)
        rows = payload.get("jobs") if isinstance(payload, dict) else None
        if not rows:
            logger.info("Remotive no devolvio ofertas")
            return []

        terms = criteria.keywords.required_any
        fuera_de_alcance = 0
        offers: list[JobOffer] = []

        for row in rows:
            if not can_work_from(row.get("candidate_required_location")):
                fuera_de_alcance += 1
                continue
            if not self._matches(row, terms):
                continue
            offers.append(self._to_offer(row))

        if fuera_de_alcance:
            logger.info("Remotive: %s ofertas no admiten candidatos desde Espana", fuera_de_alcance)

        offers.sort(key=lambda offer: offer.posted_at or date.min, reverse=True)
        return offers[: criteria.search.max_results_per_source]

    @staticmethod
    def _matches(row: dict, terms: list[str]) -> bool:
        haystack = " ".join(
            [row.get("title") or "", row.get("description") or "", *(row.get("tags") or [])]
        ).lower()
        return any(contains_term(haystack, term) for term in terms)

    def _to_offer(self, row: dict) -> JobOffer:
        posted_at = None
        if raw := row.get("publication_date"):
            try:
                posted_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
            except ValueError:
                posted_at = None

        return JobOffer(
            source=self.name,
            external_id=f"remotive:{row.get('id')}",
            title=clean_text(row.get("title")),
            company=clean_text(row.get("company_name")),
            url=row.get("url") or "",
            description=clean_text(row.get("description")),
            location=row.get("candidate_required_location") or "Worldwide",
            # Remotive only publishes remote postings.
            work_mode=WorkMode.REMOTE,
            salary=parse_salary(row.get("salary"), require_context=False),
            posted_at=posted_at,
            tags=tuple(row.get("tags") or ()),
        )
