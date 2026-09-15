"""Reads a single posting from its URL (manual mode).

Nearly every job board publishes a JSON-LD JobPosting block, because they need
it for Google for Jobs. That gives title, company, salary and description
without writing a parser per site. When it is missing, it falls back to
extracting the main text of the page.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..domain.models import JobOffer, SalaryRange
from ..domain.salary import from_bounds, parse_salary
from .http import HttpClient
from .sources.base import attr_text, clean_text, detect_work_mode

logger = logging.getLogger(__name__)

LINKEDIN_JOB_ID = re.compile(r"(?:currentJobId=|/jobs/view/[^/]*?-)(\d{6,})")
LINKEDIN_DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"


class UnreadableOffer(RuntimeError):
    """The page exists but there is no way to get a posting out of it."""


class HtmlOfferReader:
    """OfferReader implementation."""

    def __init__(self, http: HttpClient) -> None:
        self.http = http

    async def read(self, url: str) -> JobOffer:
        target = self._rewrite(url)
        try:
            html = await self.http.get_text(target)
        except Exception as exc:  # noqa: BLE001
            raise UnreadableOffer(f"No pude abrir {url}: {exc}") from exc

        soup = BeautifulSoup(html, "lxml")
        posting = self._json_ld_job_posting(soup)
        offer = self._from_json_ld(posting, url) if posting else self._from_plain_html(soup, url)
        if not offer.title:
            raise UnreadableOffer(f"No encontre ninguna oferta en {url}")
        return offer

    @staticmethod
    def from_text(text: str) -> JobOffer:
        """For when you paste the text of the posting instead of the link."""
        cleaned = clean_text(text)
        first_line = cleaned.split(".")[0][:120]
        return JobOffer(
            source="manual",
            external_id=f"manual:{abs(hash(cleaned)) % (10**12)}",
            title=first_line or "Oferta pegada a mano",
            company="",
            url="",
            description=cleaned,
            work_mode=detect_work_mode(cleaned),
            salary=parse_salary(cleaned),
        )

    @staticmethod
    def _rewrite(url: str) -> str:
        """LinkedIn does not serve the posting to a client without a session,
        but its guest endpoint does."""
        if "linkedin.com" in url:
            match = LINKEDIN_JOB_ID.search(url)
            if match:
                return LINKEDIN_DETAIL.format(job_id=match.group(1))
        return url

    @staticmethod
    def _json_ld_job_posting(soup: BeautifulSoup) -> dict | None:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                payload = json.loads(script.string or "{}")
            except (ValueError, TypeError):
                continue
            for node in payload if isinstance(payload, list) else [payload]:
                if isinstance(node, dict) and node.get("@type") == "JobPosting":
                    return node
                graph = node.get("@graph") if isinstance(node, dict) else None
                for sub in graph or []:
                    if isinstance(sub, dict) and sub.get("@type") == "JobPosting":
                        return sub
        return None

    def _from_json_ld(self, posting: dict, url: str) -> JobOffer:
        organization = posting.get("hiringOrganization") or {}
        description = clean_text(posting.get("description", ""))

        location = self._json_ld_location(posting)
        salary = self._json_ld_salary(posting)
        if not salary.is_known:
            salary = parse_salary(description)

        posted_at = None
        if raw_date := posting.get("datePosted"):
            try:
                posted_at = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00")).date()
            except ValueError:
                posted_at = None

        remote_hint = "remote" if posting.get("jobLocationType") == "TELECOMMUTE" else ""

        return JobOffer(
            source="manual",
            external_id=f"manual:{url}",
            title=clean_text(posting.get("title", "")),
            company=clean_text(organization.get("name", "")),
            url=url,
            description=description,
            location=location,
            work_mode=detect_work_mode(remote_hint, location, description[:2000]),
            salary=salary,
            posted_at=posted_at,
        )

    @staticmethod
    def _json_ld_location(posting: dict) -> str | None:
        job_location = posting.get("jobLocation")
        if isinstance(job_location, list):
            job_location = job_location[0] if job_location else None
        address = (job_location or {}).get("address") or {}
        parts = [address.get("addressLocality"), address.get("addressCountry")]
        readable = ", ".join(str(part) for part in parts if isinstance(part, str))
        return readable or None

    @staticmethod
    def _json_ld_salary(posting: dict) -> SalaryRange:
        base = posting.get("baseSalary") or {}
        value = base.get("value") or {}
        currency = base.get("currency") or value.get("currency") or "EUR"
        minimum = value.get("minValue") or value.get("value")
        maximum = value.get("maxValue")

        def as_int(raw: object) -> int | None:
            try:
                return int(float(raw))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None

        unit = str(value.get("unitText") or "").upper()
        low, high = as_int(minimum), as_int(maximum)
        if unit in {"HOUR", "DAY", "WEEK"}:
            return from_bounds(None, None, currency)
        if unit == "MONTH":
            low = low * 12 if low else None
            high = high * 12 if high else None
        return from_bounds(low, high, "EUR" if currency in {"€", "EUR"} else currency)

    @staticmethod
    def _from_plain_html(soup: BeautifulSoup, url: str) -> JobOffer:
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()

        heading = soup.find("h1") or soup.find("h2") or soup.find("title")
        body = soup.find("main") or soup.find("article") or soup.body or soup
        description = clean_text(body.get_text(" "))[:20000]

        site = soup.find("meta", property="og:site_name")
        company = clean_text(attr_text(site.get("content"))) if site else ""

        return JobOffer(
            source="manual",
            external_id=f"manual:{url}",
            title=clean_text(heading.get_text()) if heading else "",
            company=company,
            url=url,
            description=description,
            work_mode=detect_work_mode(description[:3000]),
            salary=parse_salary(description),
        )
