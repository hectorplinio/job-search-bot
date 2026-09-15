"""LinkedIn Jobs, through the public guest endpoint.

No login and no API key needed: it is the same endpoint the site uses when you
scroll while signed out. In exchange it is heavily rate-limited and the cards
carry no description, so the detail page is fetched separately, only for the
ones that pass the first cut.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace

from bs4 import BeautifulSoup

from ...domain.criteria import Criteria
from ...domain.models import JobOffer, WorkMode
from ...domain.salary import parse_salary
from ...domain.scoring import title_blockers
from .base import BaseSource, clean_text, detect_work_mode, interleave, parse_posted_at

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
_JOB_ID = re.compile(r"urn:li:jobPosting:(\d+)")

# f_TPR: time window in seconds. r604800 = the last week.
TIME_WINDOWS = {7: "r604800", 14: "r1209600", 30: "r2592000"}

# The guest endpoint serves 10 per request, no more. Without pagination you
# only saw the first ten of each search, and a posting that ranks low never
# showed up even when it was a perfect fit.
PAGE_SIZE = 10
DEFAULT_PAGES = 3

# "40 solicitudes", "Mas de 200 solicitudes", "Over 200 applicants". It only
# appears on the detail page, and in roughly half the postings.
_APPLICANTS = re.compile(r"(m[aá]s de|over)?\s*([\d.,]+)\s*(?:solicitud|applicant)", re.I)


class LinkedInSource(BaseSource):
    name = "linkedin"

    async def search(self, criteria: Criteria) -> list[JobOffer]:
        if self.has_session:
            # Warned on every run on purpose: this is the source where using
            # your account can cost you the account, and the one that gains
            # least from it.
            logger.warning(
                "LinkedIn is using your session. The guest endpoint already returns "
                "the same results without risking your profile; see README."
            )
        workplace_types = self.options.get("workplace_types") or ["2", "3"]
        window = self._time_window(criteria.search.max_age_days)
        pages = int(self.options.get("pages", DEFAULT_PAGES))

        # One group per search, so they can be interleaved later and no single
        # search hogs the source's quota.
        groups: list[list[JobOffer]] = []
        for query in self.queries(criteria):
            for location in criteria.search.locations:
                groups.append(
                    await self._search_query(
                        query, location, workplace_types, window, criteria, pages
                    )
                )

        unique = self._deduplicate(interleave(groups))

        # Dropping by title before paying for the detail page: each description
        # is one extra request. It only removes a few, but they are free to
        # remove.
        candidates = [offer for offer in unique if not title_blockers(offer.title, criteria)]

        # LinkedIn holds far more than the general cap allows: measured, the
        # configured searches return over 400 unique postings while the shared
        # limit kept 40. Its own cap lives in config.yaml, because every
        # posting kept costs one request for its description.
        limit = int(self.options.get("max_results") or criteria.search.max_results_per_source)
        logger.info(
            "LinkedIn: %d unique, %d after the title filter, keeping %d",
            len(unique),
            len(candidates),
            min(limit, len(candidates)),
        )
        return [await self._with_description(offer) for offer in candidates[:limit]]

    async def _search_query(
        self,
        query: str,
        location: str,
        workplace_types: list[str],
        window: str,
        criteria: Criteria,
        pages: int,
    ) -> list[JobOffer]:
        """One search, walking its pages until they run out."""
        encontradas: list[JobOffer] = []
        for numero in range(pages):
            pagina = await self._search_once(
                query, location, workplace_types, window, criteria, numero * PAGE_SIZE
            )
            encontradas.extend(pagina)
            # An incomplete page means there are no more results.
            if len(pagina) < PAGE_SIZE:
                break
            if len(encontradas) >= criteria.search.max_results_per_query:
                break
        return encontradas[: criteria.search.max_results_per_query]

    @staticmethod
    def _time_window(max_age_days: int) -> str:
        for days in sorted(TIME_WINDOWS):
            if max_age_days <= days:
                return TIME_WINDOWS[days]
        return TIME_WINDOWS[30]

    async def _search_once(
        self,
        query: str,
        location: str,
        workplace_types: list[str],
        window: str,
        criteria: Criteria,
        start: int = 0,
    ) -> list[JobOffer]:
        params = {
            "keywords": query,
            "location": location,
            "f_WT": ",".join(workplace_types),
            "f_TPR": window,
            "start": start,
            "sortBy": "DD",
        }
        # f_AL=true is "Easy Apply": you apply from LinkedIn, with no
        # third-party forms. It changes the result set.
        if self.options.get("easy_apply_only"):
            params["f_AL"] = "true"
        try:
            html = await self.http.get_text(SEARCH_URL, params=params, headers=self.auth_headers())
        except Exception:  # noqa: BLE001 - one failed query does not invalidate the rest
            logger.debug("LinkedIn rejected query %r in %r", query, location)
            return []

        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("div.base-card")
        offers = [self._parse_card(card) for card in cards]
        return [offer for offer in offers if offer is not None]

    def _parse_card(self, card) -> JobOffer | None:
        urn = card.get("data-entity-urn", "")
        match = _JOB_ID.search(urn)
        link = card.select_one("a.base-card__full-link")
        title = card.select_one("h3.base-search-card__title")
        company = card.select_one("h4.base-search-card__subtitle")
        if not (match and link and title and company):
            return None

        location_tag = card.select_one("span.job-search-card__location")
        salary_tag = card.select_one("span.job-search-card__salary-info")
        date_tag = card.select_one("time")

        location = clean_text(location_tag.get_text()) if location_tag else None
        posted_raw = (date_tag.get("datetime") if date_tag else None) or (
            date_tag.get_text() if date_tag else None
        )

        return JobOffer(
            source=self.name,
            external_id=f"linkedin:{match.group(1)}",
            title=clean_text(title.get_text()),
            company=clean_text(company.get_text()),
            url=link["href"].split("?")[0],
            location=location,
            work_mode=detect_work_mode(location, clean_text(title.get_text())),
            salary=parse_salary(
                clean_text(salary_tag.get_text()) if salary_tag else None, require_context=False
            ),
            posted_at=parse_posted_at(posted_raw),
        )

    @staticmethod
    def _parse_applicants(texto: str) -> int | None:
        """How many have already applied, if the detail page says so.

        "Mas de 200" is stored as 200: for deciding it makes no difference
        whether it is 200 or 340, what matters is that the queue is long.
        """
        match = _APPLICANTS.search(texto)
        if match is None:
            return None
        numero = match.group(2).replace(".", "").replace(",", "")
        return int(numero) if numero.isdigit() else None

    async def _with_description(self, offer: JobOffer) -> JobOffer:
        job_id = offer.external_id.split(":", 1)[1]
        try:
            html = await self.http.get_text(
                DETAIL_URL.format(job_id=job_id), headers=self.auth_headers()
            )
        except Exception:  # noqa: BLE001
            logger.debug("No detail page for LinkedIn %s", job_id)
            return offer

        soup = BeautifulSoup(html, "lxml")
        body = soup.select_one("div.show-more-less-html__markup") or soup
        description = clean_text(body.get_text(" "))
        criteria_items = soup.select("li.description__job-criteria-item")
        criteria_text = clean_text(" ".join(item.get_text(" ") for item in criteria_items))
        full_text = f"{description} {criteria_text}".strip()

        enriched = offer.with_description(full_text)

        solicitantes = self._parse_applicants(soup.get_text(" "))
        if solicitantes is not None:
            enriched = replace(enriched, applicants=solicitantes)

        # The card almost never carries salary or work mode; the detail page
        # does, and we have already downloaded it. Without this nearly every
        # LinkedIn posting arrives as "work mode unknown" and scores too low.
        if not enriched.salary.is_known:
            enriched = replace(enriched, salary=parse_salary(full_text))
        if enriched.work_mode is WorkMode.UNKNOWN:
            enriched = replace(
                enriched, work_mode=detect_work_mode(criteria_text, full_text[:4000])
            )
        return enriched
