"""Tecnoempleo.com.

Server-rendered HTML with no antibot protection. The cards carry title,
company, city, work mode in brackets, date and an excerpt of the description,
which is usually enough to score without opening the detail page.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ...domain.criteria import Criteria
from ...domain.models import JobOffer, WorkMode
from ...domain.salary import parse_salary
from .base import BaseSource, attr_text, clean_text, detect_work_mode, parse_posted_at

logger = logging.getLogger(__name__)

BASE = "https://www.tecnoempleo.com"
SEARCH_URL = f"{BASE}/ofertas-trabajo/"
# Detail pages hang off /<company-slug>/<technologies>/rf-<hash>
_OFFER_HREF = re.compile(r"/rf-[0-9a-f]+$")
_MODE_IN_PARENS = re.compile(r"\(([^)]+)\)")


class TecnoempleoSource(BaseSource):
    name = "tecnoempleo"

    async def search(self, criteria: Criteria) -> list[JobOffer]:
        collected: list[JobOffer] = []
        for query in self.queries(criteria):
            collected.extend(await self._search_once(query, criteria))

        offers = self._deduplicate(collected)
        if self.options.get("telework_only", True):
            offers = [
                offer
                for offer in offers
                if offer.work_mode in (WorkMode.REMOTE, WorkMode.HYBRID, WorkMode.UNKNOWN)
            ]
        return offers[: criteria.search.max_results_per_query]

    async def _search_once(self, query: str, criteria: Criteria) -> list[JobOffer]:
        try:
            html = await self.http.get_text(SEARCH_URL, params={"te": query})
        except Exception:  # noqa: BLE001
            logger.debug("Tecnoempleo fallo con la query %r", query)
            return []

        soup = BeautifulSoup(html, "lxml")
        offers: list[JobOffer] = []
        for link in soup.select("h3 a[href]"):
            if not _OFFER_HREF.search(attr_text(link.get("href"))):
                continue
            card = link.find_parent("div", class_="border")
            if card is None:
                continue
            offer = self._parse_card(card, link)
            if offer is not None:
                offers.append(offer)
        return offers[: criteria.search.max_results_per_query]

    def _parse_card(self, card, title_link) -> JobOffer | None:
        url = urljoin(BASE, title_link["href"])
        title = clean_text(title_link.get("title") or title_link.get_text())
        if not title:
            return None

        company_link = card.select_one("a.link-muted, a.text-primary")
        company = clean_text(company_link.get_text()) if company_link else ""

        # The right-hand column carries date, city, work mode and category.
        meta_blocks = [clean_text(block.get_text(" ")) for block in card.select("span")]
        meta = " | ".join(block for block in meta_blocks if block)

        tags = tuple(clean_text(badge.get_text()) for badge in card.select("span.badge"))
        description = clean_text(card.get_text(" "))

        location, work_mode = self._location_and_mode(meta)
        return JobOffer(
            source=self.name,
            external_id=f"tecnoempleo:{url.rsplit('/rf-', 1)[-1]}",
            title=title,
            company=company,
            url=url,
            description=description,
            location=location,
            work_mode=work_mode,
            salary=parse_salary(description),
            posted_at=parse_posted_at(meta),
            tags=tuple(tag for tag in tags if tag and tag.lower() != "nueva"),
        )

    @staticmethod
    def _location_and_mode(meta: str) -> tuple[str | None, WorkMode]:
        """Tecnoempleo writes 'Madrid (Híbrido)' or 'Barcelona (Teletrabajo)'."""
        match = _MODE_IN_PARENS.search(meta)
        mode_text = match.group(1) if match else ""
        city_match = re.search(r"([A-ZÁÉÍÓÚÑ][\wáéíóúñ.\- ]{2,30})\s*\(", meta)
        location = clean_text(city_match.group(1)) if city_match else None
        return location, detect_work_mode(mode_text, meta)
