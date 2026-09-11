"""Piezas comunes a todos los scrapers."""

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


def clean_text(raw: str | None) -> str:
    """Quita etiquetas HTML y colapsa espacios."""
    if not raw:
        return ""
    if "<" in raw and ">" in raw:
        raw = BeautifulSoup(raw, "lxml").get_text(" ")
    return re.sub(r"\s+", " ", raw).strip()


def detect_work_mode(*fragments: str | None) -> WorkMode:
    """Deduce la modalidad. Hibrido gana a remoto: si la oferta dice ambas,
    en la practica es hibrida."""
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
    """Entiende 'Hace 3d', 'hace 2 días', '3 days ago', '10/09/2026' y ISO."""
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


# Desde donde puedes trabajar. Algunos portales lo publican como campo
# propio, que es mucho mas fiable que adivinarlo del texto de la oferta.
WORLDWIDE_MARKERS = ("worldwide", "anywhere", "global", "any country")
EUROPE_MARKERS = ("europe", "emea", "european union", "eea")
# Las bolsas propias escriben la ciudad, no el pais: "Barcelona" a secas.
SPAIN_MARKERS = (
    "spain", "espana", "españa", "madrid", "barcelona", "valencia",
    "sevilla", "bilbao", "malaga", "málaga", "zaragoza", "alicante",
)


def can_work_from(restriction: str | None, country: str = "spain") -> bool:
    """Si una oferta remota admite a alguien que vive en `country`.

    Sin restriccion se asume mundial: los portales dejan el campo vacio cuando
    no limitan. Una oferta que solo diga "USA" se descarta aunque sea remota,
    porque remota no significa contratable desde aqui.
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
    """Mezcla los resultados de varias busquedas alternandolos.

    Sin esto, concatenar y cortar por el tope hace que la primera busqueda se
    lleve todo el cupo y las demas no lleguen a entrar nunca. Alternando, cada
    busqueda aporta sus mejores resultados antes de que nadie aporte el
    segundo.
    """
    mezclado: list[JobOffer] = []
    for posicion in range(max((len(g) for g in groups), default=0)):
        for grupo in groups:
            if posicion < len(grupo):
                mezclado.append(grupo[posicion])
    return mezclado


class BaseSource(ABC):
    """Contrato comun: `search` puede fallar, `safe_search` no."""

    name: str = "base"

    def __init__(self, http: HttpClient, options: dict | None = None) -> None:
        self.http = http
        self.options = options or {}

    @abstractmethod
    async def search(self, criteria: Criteria) -> list[JobOffer]:
        """Implementacion concreta. Puede lanzar."""

    @property
    def has_session(self) -> bool:
        """Si esta fuente va a usar tu cuenta en vez de ir de invitado."""
        return bool(self.options.get("cookie"))

    def auth_headers(self) -> dict[str, str]:
        """Cabeceras de la peticion.

        Sin cookie devuelve {} y la fuente va anonima, como hasta ahora. Con
        cookie manda tambien las cabeceras `Sec-Fetch-*` que envia un navegador
        real: una peticion con sesion pero sin ellas canta muchisimo.
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
        """Las queries de esta fuente.

        Los portales espanoles (InfoJobs, Tecnoempleo) cortan por IP si les
        encadenas seis busquedas seguidas, asi que config.yaml puede darles
        una lista mas corta y mas amplia que la general.
        """
        return self.options.get("queries") or criteria.search.queries

    async def safe_search(self, criteria: Criteria) -> list[JobOffer]:
        """Lo que llama el caso de uso. Una fuente caida no tumba la ejecucion."""
        try:
            offers = await self.search(criteria)
        except Exception:  # noqa: BLE001 - una fuente rota no puede parar al resto
            logger.exception("La fuente %s fallo; se ignora en esta ejecucion", self.name)
            return []
        session = " (con sesion)" if self.has_session else ""
        logger.info("%s%s: %s ofertas", self.name, session, len(offers))
        return offers

    def _deduplicate(self, offers: list[JobOffer]) -> list[JobOffer]:
        """Quita repetidos dentro de la propia fuente (varias queries la traen)."""
        seen: set[str] = set()
        unique: list[JobOffer] = []
        for offer in offers:
            if offer.external_id in seen:
                continue
            seen.add(offer.external_id)
            unique.append(offer)
        return unique
