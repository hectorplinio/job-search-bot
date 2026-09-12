"""LinkedIn Jobs, via el endpoint publico de invitado.

No hace falta login ni API key: es el mismo endpoint que usa la web cuando
haces scroll sin estar logueado. A cambio, limita bastante y las tarjetas no
traen descripcion, asi que la ficha se pide aparte solo para las que pasan
el primer corte.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace

from bs4 import BeautifulSoup

from ...domain.criteria import Criteria
from ...domain.models import JobOffer, WorkMode
from ...domain.salary import parse_salary
from .base import BaseSource, clean_text, detect_work_mode, interleave, parse_posted_at

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
_JOB_ID = re.compile(r"urn:li:jobPosting:(\d+)")

# f_TPR: ventana temporal en segundos. r604800 = ultima semana.
TIME_WINDOWS = {7: "r604800", 14: "r1209600", 30: "r2592000"}

# El endpoint de invitado sirve 10 por peticion, no mas. Sin paginar solo se
# veian las diez primeras de cada busqueda, y una oferta que rankee baja no
# aparecia jamas aunque encajara perfectamente.
PAGE_SIZE = 10
DEFAULT_PAGES = 3

# "40 solicitudes", "Mas de 200 solicitudes", "Over 200 applicants". Solo sale
# en la ficha, y aproximadamente en la mitad de las ofertas.
_APPLICANTS = re.compile(r"(m[aá]s de|over)?\s*([\d.,]+)\s*(?:solicitud|applicant)", re.I)


class LinkedInSource(BaseSource):
    name = "linkedin"

    async def search(self, criteria: Criteria) -> list[JobOffer]:
        if self.has_session:
            # Aviso a proposito en cada ejecucion: es la fuente donde usar tu
            # cuenta te puede costar la cuenta, y la que menos gana con ello.
            logger.warning(
                "LinkedIn va con tu sesion. El endpoint de invitado ya devuelve "
                "los mismos resultados sin arriesgar el perfil; ver README."
            )
        workplace_types = self.options.get("workplace_types") or ["2", "3"]
        window = self._time_window(criteria.search.max_age_days)
        pages = int(self.options.get("pages", DEFAULT_PAGES))

        # Un grupo por busqueda, para luego alternarlos y que ninguna acapare
        # el cupo de la fuente.
        groups: list[list[JobOffer]] = []
        for query in self.queries(criteria):
            for location in criteria.search.locations:
                groups.append(
                    await self._search_query(
                        query, location, workplace_types, window, criteria, pages
                    )
                )

        unique = self._deduplicate(interleave(groups))
        limit = criteria.search.max_results_per_source
        return [await self._with_description(offer) for offer in unique[:limit]]

    async def _search_query(
        self,
        query: str,
        location: str,
        workplace_types: list[str],
        window: str,
        criteria: Criteria,
        pages: int,
    ) -> list[JobOffer]:
        """Una busqueda, recorriendo sus paginas hasta agotarlas."""
        encontradas: list[JobOffer] = []
        for numero in range(pages):
            pagina = await self._search_once(
                query, location, workplace_types, window, criteria, numero * PAGE_SIZE
            )
            encontradas.extend(pagina)
            # Una pagina incompleta significa que no hay mas resultados.
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
        # f_AL=true es "Solicitud sencilla": se aplica desde LinkedIn, sin
        # formularios de terceros. Cambia el conjunto de resultados.
        if self.options.get("easy_apply_only"):
            params["f_AL"] = "true"
        try:
            html = await self.http.get_text(
                SEARCH_URL, params=params, headers=self.auth_headers()
            )
        except Exception:  # noqa: BLE001 - una query fallida no invalida el resto
            logger.debug("LinkedIn rechazo la query %r en %r", query, location)
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
            salary=parse_salary(clean_text(salary_tag.get_text()) if salary_tag else None,
                                require_context=False),
            posted_at=parse_posted_at(posted_raw),
        )

    @staticmethod
    def _parse_applicants(texto: str) -> int | None:
        """Cuantos han solicitado ya, si la ficha lo dice.

        "Mas de 200" se guarda como 200: para decidir da igual si son 200 o
        340, lo que importa es que la cola es larga.
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
            logger.debug("Sin ficha para LinkedIn %s", job_id)
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

        # La tarjeta casi nunca trae salario ni modalidad; la ficha si, y ya
        # la hemos descargado. Sin esto casi todas las ofertas de LinkedIn
        # llegan como "Modalidad sin especificar" y puntuan de menos.
        if not enriched.salary.is_known:
            enriched = replace(enriched, salary=parse_salary(full_text))
        if enriched.work_mode is WorkMode.UNKNOWN:
            enriched = replace(
                enriched, work_mode=detect_work_mode(criteria_text, full_text[:4000])
            )
        return enriched
