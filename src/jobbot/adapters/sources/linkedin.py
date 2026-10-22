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

# For the companies you follow (sources.linkedin.companies).
DEFAULT_COMPANY_MAX_AGE_DAYS = 7
DEFAULT_COMPANY_MAX_RESULTS = 100

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

        # The consultancies you follow. Capitole and the like publish only on
        # LinkedIn, and the keyword searches miss most of their postings
        # because LinkedIn ranks them low. Searching by company id (f_C)
        # catches them all.
        #
        # With dozens of companies, reading each whole board would be too many
        # requests for LinkedIn: a consultancy's board is mostly SAP, .NET and
        # electrical engineering, and each card kept costs one more request for
        # its description. So each company is searched once, only where you
        # can work, with your required keywords joined by OR.
        #
        # And only over the last week: the bot runs every few hours, so an
        # older posting was already read on an earlier run. Measured with 52
        # consultancies, the 30-day window gave 501 postings to fetch, about
        # twelve minutes of detail pages on every run.
        company_keywords = " OR ".join(criteria.keywords.required_any)
        company_locations = self.options.get("company_locations") or ["Spain"]
        company_window = self._time_window(
            int(self.options.get("company_max_age_days") or DEFAULT_COMPANY_MAX_AGE_DAYS)
        )
        company_groups: list[list[JobOffer]] = []
        for company in self.options.get("companies") or []:
            company_id = str(company.get("id") or "").strip()
            if not company_id:
                continue
            for location in company_locations:
                company_groups.append(
                    await self._search_query(
                        company_keywords,
                        location,
                        workplace_types,
                        company_window,
                        criteria,
                        pages,
                        company_id,
                    )
                )

        unique = self._deduplicate(interleave(groups))
        from_companies = self._deduplicate(interleave(company_groups))

        # Dropping by title before paying for the detail page: each description
        # is one extra request. It only removes a few, but they are free to
        # remove.
        candidates = [offer for offer in unique if not title_blockers(offer.title, criteria)]
        company_candidates = [
            offer for offer in from_companies if not title_blockers(offer.title, criteria)
        ]

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
        # The companies you follow have a cap of their own instead: you asked
        # for them by name, so a busy day on the general searches must not
        # push them out. They come interleaved, so a big board like Accenture's
        # cannot take the whole cap from the small ones either.
        company_limit = int(self.options.get("company_max_results") or DEFAULT_COMPANY_MAX_RESULTS)
        if company_candidates:
            logger.info(
                "LinkedIn: %d more from the companies you follow, keeping %d",
                len(company_candidates),
                min(company_limit, len(company_candidates)),
            )
        kept = self._deduplicate(company_candidates[:company_limit] + candidates[:limit])
        return [await self._with_description(offer) for offer in kept]

    async def _search_query(
        self,
        query: str,
        location: str,
        workplace_types: list[str],
        window: str,
        criteria: Criteria,
        pages: int,
        company_id: str | None = None,
    ) -> list[JobOffer]:
        """One search, walking its pages until they run out."""
        encontradas: list[JobOffer] = []
        for numero in range(pages):
            pagina = await self._search_once(
                query, location, workplace_types, window, criteria, numero * PAGE_SIZE, company_id
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
        company_id: str | None = None,
    ) -> list[JobOffer]:
        params: dict[str, str | int] = {
            "location": location,
            "f_WT": ",".join(workplace_types),
            "f_TPR": window,
            "start": start,
            "sortBy": "DD",
        }
        # Empty keywords are left out rather than sent blank.
        if query:
            params["keywords"] = query
        if company_id:
            params["f_C"] = company_id
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
