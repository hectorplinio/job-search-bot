"""We Work Remotely, via sus feeds RSS publicos.

Es la fuente mas barata de mantener: RSS estable, sin antibot y sin clave. El
titulo viene como "Empresa: Puesto" y el salario, cuando existe, va dentro de
la descripcion.
"""

from __future__ import annotations

import logging
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

from ...domain.criteria import Criteria
from ...domain.models import JobOffer, WorkMode
from ...domain.salary import parse_salary
from ...domain.scoring import contains_term
from .base import BaseSource, clean_text

logger = logging.getLogger(__name__)

DEFAULT_FEEDS = (
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
)


class WeWorkRemotelySource(BaseSource):
    name = "weworkremotely"

    async def search(self, criteria: Criteria) -> list[JobOffer]:
        feeds = self.options.get("feeds") or list(DEFAULT_FEEDS)
        collected: list[JobOffer] = []
        for feed in feeds:
            collected.extend(await self._read_feed(feed, criteria))

        return self._deduplicate(collected)[: criteria.search.max_results_per_query]

    async def _read_feed(self, url: str, criteria: Criteria) -> list[JobOffer]:
        try:
            xml = await self.http.get_text(url)
        except Exception:  # noqa: BLE001
            logger.debug("No se pudo leer el feed %s", url)
            return []

        soup = BeautifulSoup(xml, "xml")
        offers: list[JobOffer] = []
        for item in soup.find_all("item"):
            offer = self._parse_item(item)
            if offer is None:
                continue
            if any(
                contains_term(offer.searchable_text, term)
                for term in criteria.keywords.required_any
            ):
                offers.append(offer)
        return offers

    def _parse_item(self, item) -> JobOffer | None:
        link_tag = item.find("link")
        title_tag = item.find("title")
        if link_tag is None or title_tag is None:
            return None

        link = clean_text(link_tag.get_text())
        raw_title = clean_text(title_tag.get_text())
        # WWR titula "Empresa: Puesto".
        company, _, title = raw_title.partition(":")
        if not title:
            company, title = "", raw_title

        description_tag = item.find("description")
        description = clean_text(description_tag.get_text()) if description_tag else ""

        region_tag = item.find("region")
        region = clean_text(region_tag.get_text()) if region_tag else "Remote"

        posted_at = None
        date_tag = item.find("pubDate")
        if date_tag is not None:
            try:
                posted_at = parsedate_to_datetime(date_tag.get_text().strip()).date()
            except (TypeError, ValueError):
                posted_at = None

        return JobOffer(
            source=self.name,
            external_id=f"wwr:{link.rstrip('/').rsplit('/', 1)[-1]}",
            title=title.strip(),
            company=company.strip(),
            url=link,
            description=description,
            location=region,
            work_mode=WorkMode.REMOTE,
            salary=parse_salary(description),
            posted_at=posted_at,
        )
