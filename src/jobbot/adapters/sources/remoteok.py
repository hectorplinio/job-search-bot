"""RemoteOK.

A public JSON API, no key, with salaries in dollars and everything remote by
definition. It covers the international gap Otta left open.
"""

from __future__ import annotations

import logging
from datetime import datetime

from ...domain.criteria import Criteria
from ...domain.models import JobOffer, WorkMode
from ...domain.salary import from_bounds
from ...domain.scoring import contains_term
from .base import BaseSource, clean_text

logger = logging.getLogger(__name__)

API_URL = "https://remoteok.com/api"


class RemoteOkSource(BaseSource):
    name = "remoteok"

    async def search(self, criteria: Criteria) -> list[JobOffer]:
        payload = await self.http.get_json(API_URL)
        if not isinstance(payload, list):
            return []

        # The first array item is RemoteOK's legal notice, not a posting.
        rows = [row for row in payload if isinstance(row, dict) and row.get("id")]

        terms = criteria.keywords.required_any
        matching = [row for row in rows if self._matches(row, terms)]
        matching.sort(key=lambda row: row.get("epoch") or 0, reverse=True)

        offers = [self._to_offer(row) for row in matching]
        return offers[: criteria.search.max_results_per_query]

    @staticmethod
    def _matches(row: dict, terms: list[str]) -> bool:
        haystack = " ".join(
            [row.get("position") or "", row.get("description") or "", *(row.get("tags") or [])]
        ).lower()
        return any(contains_term(haystack, term) for term in terms)

    def _to_offer(self, row: dict) -> JobOffer:
        posted_at = None
        if raw_date := row.get("date"):
            try:
                posted_at = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00")).date()
            except ValueError:
                posted_at = None

        return JobOffer(
            source=self.name,
            external_id=f"remoteok:{row['id']}",
            title=clean_text(row.get("position")),
            company=clean_text(row.get("company")),
            url=row.get("url") or f"https://remoteok.com/remote-jobs/{row['id']}",
            description=clean_text(row.get("description")),
            location=clean_text(row.get("location")) or "Remote",
            work_mode=WorkMode.REMOTE,
            salary=from_bounds(row.get("salary_min"), row.get("salary_max"), "USD"),
            posted_at=posted_at,
            tags=tuple(row.get("tags") or ()),
        )
