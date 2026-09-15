"""Glassdoor.

The most fragile source of the lot: their class names carry a hash that changes
with every deploy of theirs, so we select on `data-test` attributes, which are
stable. If they ever stop serving HTML without JavaScript, this source will
return zero postings and the rest will keep running.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ...domain.criteria import Criteria
from ...domain.models import JobOffer
from ...domain.salary import parse_salary
from .base import BaseSource, clean_text, detect_work_mode, parse_posted_at

logger = logging.getLogger(__name__)

BASE = "https://www.glassdoor.es"
# Glassdoor's internal country id in their URLs. 219 = Spain.
DEFAULT_COUNTRY_ID = 219
DEFAULT_LOCATION_SLUG = "espana"
_JOB_ID = re.compile(r"jl=(\d+)")


class GlassdoorSource(BaseSource):
    name = "glassdoor"

    async def search(self, criteria: Criteria) -> list[JobOffer]:
        collected: list[JobOffer] = []
        for query in self.queries(criteria):
            collected.extend(await self._search_once(query, criteria))
        return self._deduplicate(collected)[: criteria.search.max_results_per_query]

    def _build_url(self, query: str) -> str:
        """Glassdoor encodes the country and role offsets in the URL.

        'espana-python-empleos-SRCH_IL.0,6_IN219_KO7,13' means: the country
        takes characters 0-6 of the slug and the role takes 7-13.
        """
        location = self.options.get("location_slug", DEFAULT_LOCATION_SLUG)
        country_id = self.options.get("country_id", DEFAULT_COUNTRY_ID)
        keyword = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")

        location_end = len(location)
        keyword_start = location_end + 1
        keyword_end = keyword_start + len(keyword)
        slug = f"{location}-{keyword}-empleos"
        code = f"SRCH_IL.0,{location_end}_IN{country_id}_KO{keyword_start},{keyword_end}.htm"
        return f"{BASE}/Empleo/{slug}-{code}"

    async def _search_once(self, query: str, criteria: Criteria) -> list[JobOffer]:
        url = self._build_url(query)
        try:
            html = await self.http.get_text(url, headers=self.auth_headers())
        except Exception as exc:  # noqa: BLE001
            # A 403 is their antibot, not a bug: they block your IP after a few
            # requests. With GLASSDOOR_COOKIE in .env they stop treating you
            # as an anonymous visitor.
            hint = "" if self.has_session else " (prueba con GLASSDOOR_COOKIE en .env)"
            logger.warning("Glassdoor rejected %r (%s)%s", query, str(exc)[:60], hint)
            return []

        soup = BeautifulSoup(html, "lxml")
        offers: list[JobOffer] = []
        for title_tag in soup.select('a[data-test="job-title"]'):
            offer = self._parse_card(title_tag)
            if offer is not None:
                offers.append(offer)
        if not offers:
            logger.info("Glassdoor returned no cards for %r (possibly blocked)", query)
        return offers[: criteria.search.max_results_per_query]

    def _parse_card(self, title_tag) -> JobOffer | None:
        href = title_tag.get("href") or ""
        match = _JOB_ID.search(href) or re.search(r"job-listing/([^?]+)", href)
        if match is None:
            return None

        card = title_tag.find_parent("div", class_=re.compile("JobCard")) or title_tag.parent
        company_tag = card.select_one(
            '[data-test="employer-short-name"], [data-test="employerName"]'
        )
        location_tag = card.select_one('[data-test="emp-location"]')
        salary_tag = card.select_one('[data-test="detailSalary"]')
        age_tag = card.select_one('[data-test="job-age"]')
        snippet_tag = card.select_one('[data-test="descSnippet"]')

        location = clean_text(location_tag.get_text()) if location_tag else None
        snippet = clean_text(snippet_tag.get_text(" ")) if snippet_tag else ""
        salary_text = clean_text(salary_tag.get_text()) if salary_tag else ""
        salary = parse_salary(salary_text, require_context=False)
        if not salary.is_known:
            salary = parse_salary(snippet)

        return JobOffer(
            source=self.name,
            external_id=f"glassdoor:{match.group(1)}",
            title=clean_text(title_tag.get_text()),
            company=clean_text(company_tag.get_text()) if company_tag else "",
            url=urljoin(BASE, href.split("?")[0]),
            description=snippet,
            location=location,
            work_mode=detect_work_mode(location, snippet, clean_text(title_tag.get_text())),
            salary=salary,
            posted_at=parse_posted_at(clean_text(age_tag.get_text()) if age_tag else None),
        )
