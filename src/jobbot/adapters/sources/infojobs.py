"""InfoJobs.

La pagina de resultados llega renderizada desde servidor, con clases
`ij-OfferCardContent-*` estables y un span dedicado al salario cuando la
empresa lo publica. No hace falta la API oficial (que ya no dan de alta).
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from ...domain.criteria import Criteria
from ...domain.models import JobOffer
from ...domain.salary import parse_salary
from .base import BaseSource, clean_text, detect_work_mode, parse_posted_at

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.infojobs.net/jobsearch/search-results/list.xhtml"
_OFFER_ID = re.compile(r"/of-i([0-9a-f]+)")


class InfoJobsSource(BaseSource):
    name = "infojobs"

    async def search(self, criteria: Criteria) -> list[JobOffer]:
        collected: list[JobOffer] = []
        for query in self.queries(criteria):
            collected.extend(await self._search_once(query, criteria))
        return self._deduplicate(collected)[: criteria.search.max_results_per_query]

    async def _search_once(self, query: str, criteria: Criteria) -> list[JobOffer]:
        params = {"keyword": query, "sortBy": "PUBLICATION_DATE", "page": 1}
        try:
            html = await self.http.get_text(SEARCH_URL, params=params, headers=self.auth_headers())
        except Exception:  # noqa: BLE001
            logger.debug("InfoJobs fallo con la query %r", query)
            return []

        soup = BeautifulSoup(html, "lxml")
        offers: list[JobOffer] = []
        for card in soup.select("div.ij-OfferCardContent-description"):
            offer = self._parse_card(card)
            if offer is not None:
                offers.append(offer)

        if not offers:
            # InfoJobs no da 403: sirve una pagina corta sin tarjetas. Sin ese
            # aviso parece que simplemente no hay ofertas de lo que buscas.
            logger.info(
                "InfoJobs no devolvio tarjetas para %r (%s bytes). "
                "Suele ser limitacion por IP; con INFOJOBS_COOKIE en .env va mejor.",
                query,
                len(html),
            )
        return offers[: criteria.search.max_results_per_query]

    def _parse_card(self, card) -> JobOffer | None:
        title_link = card.select_one("a.ij-OfferCardContent-description-link")
        if title_link is None or not title_link.get("href"):
            return None

        href = title_link["href"]
        url = f"https:{href}" if href.startswith("//") else href
        match = _OFFER_ID.search(url)
        if match is None:
            return None

        company_tag = card.select_one("a.ij-OfferCardContent-description-subtitle-link")
        salary_tag = card.select_one("span.ij-OfferCardContent-description-salary-info")
        snippet_tag = card.select_one("p.ij-OfferCardContent-description-description")

        items = [
            clean_text(item.get_text(" "))
            for item in card.select("li.ij-OfferCardContent-description-list-item")
        ]
        meta = " | ".join(item for item in items if item)
        # El primer item es la provincia; el segundo suele ser la modalidad.
        location = items[0] if items else None
        snippet = clean_text(snippet_tag.get_text(" ")) if snippet_tag else ""
        salary_text = clean_text(salary_tag.get_text(" ")) if salary_tag else ""

        description = " ".join(part for part in (meta, snippet) if part)
        salary = parse_salary(salary_text, require_context=False)
        if not salary.is_known:
            salary = parse_salary(description)

        return JobOffer(
            source=self.name,
            external_id=f"infojobs:{match.group(1)}",
            title=clean_text(title_link.get("aria-label") or title_link.get_text()),
            company=clean_text(company_tag.get_text()) if company_tag else "",
            url=url.split("?")[0],
            description=description,
            location=location,
            work_mode=detect_work_mode(meta, snippet),
            salary=salary,
            posted_at=parse_posted_at(meta),
        )
