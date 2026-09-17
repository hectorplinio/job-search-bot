"""Manfred (getmanfred.com).

The best source of the lot: a public JSON API, with the salary range and the
remote percentage in the listing itself, so the salary filter works before
downloading anything else. The description comes from the detail page, only
for postings that already passed the first cut.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from ...domain.criteria import Criteria
from ...domain.models import JobOffer, WorkMode
from ...domain.salary import from_bounds
from ...domain.scoring import contains_term
from .base import BaseSource, clean_text

logger = logging.getLogger(__name__)

LIST_URL = "https://www.getmanfred.com/api/v2/public/offers"
OFFER_URL = "https://www.getmanfred.com/ofertas-empleo/{id}/{slug}"
_NEXT_DATA = re.compile(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)


class ManfredSource(BaseSource):
    name = "manfred"

    async def search(self, criteria: Criteria) -> list[JobOffer]:
        payload = await self.http.get_json(LIST_URL, params={"lang": "ES"})
        if not isinstance(payload, list):
            logger.warning("Manfred returned an unexpected payload")
            return []

        terms = criteria.keywords.required_any
        shortlist = [
            raw
            for raw in payload
            if raw.get("status") == "ACTIVE" and self._matches_terms(raw, terms)
        ]
        shortlist.sort(key=lambda raw: raw.get("updatedAt") or "", reverse=True)
        shortlist = shortlist[: criteria.search.max_results_per_query]

        offers = [self._to_offer(raw) for raw in shortlist]
        return [await self._with_description(offer) for offer in offers]

    @staticmethod
    def _matches_terms(raw: dict, terms: list[str]) -> bool:
        haystack = " ".join(
            [raw.get("position") or "", raw.get("slug") or "", *(raw.get("highlights") or [])]
        ).lower()
        return any(contains_term(haystack, term) for term in terms)

    def _to_offer(self, raw: dict) -> JobOffer:
        remote_pct = raw.get("remotePercentage") or 0
        if remote_pct >= 90:
            work_mode = WorkMode.REMOTE
        elif remote_pct > 0:
            work_mode = WorkMode.HYBRID
        else:
            work_mode = WorkMode.ONSITE

        currency = "EUR" if (raw.get("currency") or "€") == "€" else raw["currency"]
        locations = raw.get("locations") or []

        posted_at = None
        if updated := raw.get("updatedAt"):
            with_zone = updated.replace("Z", "+00:00")
            try:
                posted_at = datetime.fromisoformat(with_zone).date()
            except ValueError:
                posted_at = None

        return JobOffer(
            source=self.name,
            external_id=f"manfred:{raw['id']}",
            title=raw.get("position") or "",
            company=(raw.get("company") or {}).get("name") or "",
            url=OFFER_URL.format(id=raw["id"], slug=raw.get("slug", "")),
            location=", ".join(locations) if locations else None,
            work_mode=work_mode,
            salary=from_bounds(raw.get("salaryFrom"), raw.get("salaryTo"), currency),
            posted_at=posted_at,
            tags=tuple(raw.get("highlights") or ()),
        )

    async def _with_description(self, offer: JobOffer) -> JobOffer:
        """The detail page carries a JSON-LD JobPosting block with the full text."""
        try:
            html = await self.http.get_text(offer.url)
        except Exception:  # noqa: BLE001 - without a description the posting is still worth keeping
            logger.debug("Could not read the detail page for %s", offer.url)
            return offer

        match = _NEXT_DATA.search(html)
        if not match:
            return offer
        try:
            page_props = json.loads(match.group(1))["props"]["pageProps"]
            job_posting = json.loads(page_props["offer"]["jsonld"])
        except (KeyError, ValueError, TypeError):
            return offer

        return offer.with_description(clean_text(job_posting.get("description", "")))
