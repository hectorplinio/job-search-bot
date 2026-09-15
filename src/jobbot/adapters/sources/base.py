"""Pieces shared by every scraper."""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from datetime import date, timedelta

from bs4 import BeautifulSoup

from ...domain.criteria import Criteria
from ...domain.models import JobOffer, WorkMode
from ..http import HttpClient

logger = logging.getLogger(__name__)

HYBRID_MARKERS = ("hibrido", "híbrido", "hybrid", "semipresencial", "teletrabajo parcial")
REMOTE_MARKERS = (
    "100% remoto",
    "100% remote",
    "fully remote",
    "remote first",
    "teletrabajo total",
    "teletrabajo 100",
    "en remoto",
    "remoto",
    "remote",
    "teletrabajo",
    "work from home",
    "anywhere",
)
ONSITE_MARKERS = ("presencial", "on-site", "onsite", "in office", "in-office")


def attr_text(value: object) -> str:
    """An HTML attribute value as a string.

    BeautifulSoup returns a list when the attribute takes several values
    (`class`, `rel`), so the types are `str | list[str] | None`.
    """
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(str(item) for item in value)
    return str(value)


def clean_text(raw: str | None) -> str:
    """Strips HTML tags and collapses whitespace."""
    if not raw:
        return ""
    if "<" in raw and ">" in raw:
        raw = BeautifulSoup(raw, "lxml").get_text(" ")
    return re.sub(r"\s+", " ", raw).strip()


def detect_work_mode(*fragments: str | None) -> WorkMode:
    """Works out the work mode. Hybrid beats remote: if a posting says both,
    in practice it is hybrid."""
    text = " ".join(fragment.lower() for fragment in fragments if fragment)
    if not text:
        return WorkMode.UNKNOWN
    if any(marker in text for marker in HYBRID_MARKERS):
        return WorkMode.HYBRID
    if any(marker in text for marker in REMOTE_MARKERS):
        return WorkMode.REMOTE
    if any(marker in text for marker in ONSITE_MARKERS):
        return WorkMode.ONSITE
    return WorkMode.UNKNOWN


_RELATIVE = re.compile(
    r"(?:hace|posted|)\s*(\d+)\s*(minuto|minute|hora|hour|d[ií]a|day|semana|week|mes|month)",
    re.IGNORECASE,
)
_RELATIVE_SHORT = re.compile(r"hace\s*(\d+)\s*([mhdsw])\b", re.IGNORECASE)
_ABSOLUTE_ES = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_ABSOLUTE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

_UNIT_DAYS = {
    "minuto": 0,
    "minute": 0,
    "m": 0,
    "hora": 0,
    "hour": 0,
    "h": 0,
    "dia": 1,
    "día": 1,
    "day": 1,
    "d": 1,
    "semana": 7,
    "week": 7,
    "s": 7,
    "w": 7,
    "mes": 30,
    "month": 30,
}


def parse_posted_at(text: str | None, today: date | None = None) -> date | None:
    """Understands 'Hace 3d', 'hace 2 días', '3 days ago', '10/09/2026' and ISO."""
    if not text:
        return None
    today = today or date.today()

    iso = _ABSOLUTE_ISO.search(text)
    if iso:
        year, month, day = (int(part) for part in iso.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None

    spanish = _ABSOLUTE_ES.search(text)
    if spanish:
        day, month, year = (int(part) for part in spanish.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None

    for pattern in (_RELATIVE, _RELATIVE_SHORT):
        match = pattern.search(text)
        if match:
            amount = int(match.group(1))
            unit = match.group(2).lower()
            days = _UNIT_DAYS.get(unit, _UNIT_DAYS.get(unit.rstrip("s"), 0))
            return today - timedelta(days=amount * days)

    if re.search(r"\b(hoy|today|just now|ahora)\b", text, re.IGNORECASE):
        return today
    if re.search(r"\b(ayer|yesterday)\b", text, re.IGNORECASE):
        return today - timedelta(days=1)
    return None


# Where you are allowed to work from. Some boards publish this as a field of
# its own, which is far more reliable than guessing from the posting text.
WORLDWIDE_MARKERS = ("worldwide", "anywhere", "global", "any country")
EUROPE_MARKERS = ("europe", "emea", "european union", "eea")
# Company boards write the city, not the country: plain "Barcelona".
SPAIN_MARKERS = (
    "spain",
    "espana",
    "españa",
    "madrid",
    "barcelona",
    "valencia",
    "sevilla",
    "bilbao",
    "malaga",
    "málaga",
    "zaragoza",
    "alicante",
)


def can_work_from(restriction: str | None, country: str = "spain") -> bool:
    """Whether a remote posting accepts someone living in `country`.

    With no restriction, worldwide is assumed: boards leave the field empty
    when they do not limit it. A posting that only says "USA" is rejected even
    if it is remote, because remote does not mean hireable from here.
    """
    if not restriction or not restriction.strip():
        return True
    texto = restriction.lower()
    if any(marker in texto for marker in WORLDWIDE_MARKERS):
        return True
    if country in texto or any(marker in texto for marker in SPAIN_MARKERS):
        return True
    return any(marker in texto for marker in EUROPE_MARKERS)


def interleave(groups: list[list[JobOffer]]) -> list[JobOffer]:
    """Interleaves the results of several searches.

    Without this, concatenating and truncating at the cap means the first
    search takes the whole quota and the rest never get in. Interleaved, every
    search contributes its best results before anyone contributes a second.
    """
    mezclado: list[JobOffer] = []
    for posicion in range(max((len(g) for g in groups), default=0)):
        for grupo in groups:
            if posicion < len(grupo):
                mezclado.append(grupo[posicion])
    return mezclado


class BaseSource(ABC):
    """The shared contract: `search` may fail, `safe_search` may not."""

    name: str = "base"

    def __init__(self, http: HttpClient, options: dict | None = None) -> None:
        self.http = http
        self.options = options or {}

    @abstractmethod
    async def search(self, criteria: Criteria) -> list[JobOffer]:
        """The concrete implementation. It may raise."""

    @property
    def has_session(self) -> bool:
        """Whether this source will use your account instead of going as a guest."""
        return bool(self.options.get("cookie"))

    def auth_headers(self) -> dict[str, str]:
        """The request headers.

        With no cookie it returns {} and the source goes anonymous, as before.
        With a cookie it also sends the `Sec-Fetch-*` headers a real browser
        sends: a request with a session but without them stands out a mile.
        """
        cookie = self.options.get("cookie")
        if not cookie:
            return {}
        return {
            "Cookie": cookie,
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }

    def queries(self, criteria: Criteria) -> list[str]:
        """This source's queries.

        The Spanish boards (InfoJobs, Tecnoempleo) block your IP if you chain
        six searches in a row, so config.yaml can give them a shorter, broader
        list than the general one.
        """
        return self.options.get("queries") or criteria.search.queries

    async def safe_search(self, criteria: Criteria) -> list[JobOffer]:
        """What the use case calls. A source that is down does not sink the run."""
        try:
            offers = await self.search(criteria)
        except Exception:  # noqa: BLE001 - one broken source must not stop the others
            logger.exception("Source %s failed; skipping it on this run", self.name)
            return []
        session = " (with session)" if self.has_session else ""
        logger.info("%s%s: %s postings", self.name, session, len(offers))
        return offers

    def _deduplicate(self, offers: list[JobOffer]) -> list[JobOffer]:
        """Drops repeats within the source itself (several queries return it)."""
        seen: set[str] = set()
        unique: list[JobOffer] = []
        for offer in offers:
            if offer.external_id in seen:
                continue
            seen.add(offer.external_id)
            unique.append(offer)
        return unique
