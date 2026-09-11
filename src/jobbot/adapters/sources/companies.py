"""Bolsas de empleo propias de las empresas que te interesan.

Es la fuente mas valiosa del proyecto, y la mas aburrida: casi toda empresa
tech publica a traves de Greenhouse o Ashby, y los dos exponen la bolsa entera
en JSON, sin clave y sin antibot.

Tres ventajas sobre cualquier agregador:

1. La oferta aparece aqui antes que en ningun otro sitio.
2. Viene con la ubicacion real. Grafana Labs publica el mismo puesto por pais,
   asi que se ve directamente cual es el de Espana, en vez de encontrarte el
   de Irlanda y tener que averiguar si admiten a alguien de aqui.
3. No hay ranking que esconda nada: se lee el catalogo completo.

A cambio hay que decirle que empresas mirar. Eso esta en config.yaml, en
`sources.companies.watchlist`.

Para anadir una empresa, busca su pagina de empleo y mira la URL:
    job-boards.greenhouse.io/EMPRESA  ->  ats: greenhouse, slug: EMPRESA
    jobs.ashbyhq.com/EMPRESA          ->  ats: ashby,      slug: EMPRESA
"""

from __future__ import annotations

import logging
from datetime import datetime

from ...domain.criteria import Criteria
from ...domain.models import JobOffer, WorkMode
from ...domain.salary import parse_salary
from ...domain.scoring import contains_term
from .base import BaseSource, can_work_from, clean_text, detect_work_mode, interleave

logger = logging.getLogger(__name__)

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


class CompaniesSource(BaseSource):
    name = "companies"

    async def search(self, criteria: Criteria) -> list[JobOffer]:
        watchlist = self.options.get("watchlist") or []
        if not watchlist:
            logger.info(
                "La fuente companies no tiene empresas que mirar. "
                "Anadelas en sources.companies.watchlist de config.yaml."
            )
            return []

        grupos: list[list[JobOffer]] = []
        for empresa in watchlist:
            grupos.append(await self._read_board(empresa, criteria))

        unicas = self._deduplicate(interleave(grupos))
        return unicas[: criteria.search.max_results_per_source]

    async def _read_board(self, empresa: dict, criteria: Criteria) -> list[JobOffer]:
        ats = (empresa.get("ats") or "greenhouse").lower()
        slug = empresa.get("slug")
        if not slug:
            return []

        lectores = {"greenhouse": self._read_greenhouse, "ashby": self._read_ashby}
        lector = lectores.get(ats)
        if lector is None:
            logger.warning("No se leer bolsas de tipo %r (empresa %s)", ats, slug)
            return []

        try:
            ofertas = await lector(empresa, slug)
        except Exception as exc:  # noqa: BLE001 - una empresa caida no anula las demas
            logger.warning("No pude leer la bolsa de %s (%s)", slug, str(exc)[:70])
            return []

        terms = criteria.keywords.required_any
        aptas = [
            oferta
            for oferta in ofertas
            if can_work_from(oferta.location)
            and any(contains_term(oferta.searchable_text, term) for term in terms)
        ]
        if ofertas:
            logger.info(
                "%s: %s ofertas en su bolsa, %s aptas para ti", slug, len(ofertas), len(aptas)
            )
        return aptas[: criteria.search.max_results_per_query]

    async def _read_greenhouse(self, empresa: dict, slug: str) -> list[JobOffer]:
        payload = await self.http.get_json(GREENHOUSE_URL.format(slug=slug))
        nombre = empresa.get("name") or slug
        return [self._from_greenhouse(row, nombre, slug) for row in payload.get("jobs", [])]

    def _from_greenhouse(self, row: dict, nombre: str, slug: str) -> JobOffer:
        ubicacion = (row.get("location") or {}).get("name") or ""
        descripcion = clean_text(row.get("content"))

        publicada = None
        if raw := (row.get("first_published") or row.get("updated_at")):
            try:
                publicada = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
            except ValueError:
                publicada = None

        return JobOffer(
            source=self.name,
            external_id=f"greenhouse:{slug}:{row.get('id')}",
            title=clean_text(row.get("title")),
            company=nombre,
            url=row.get("absolute_url") or "",
            description=descripcion,
            location=ubicacion,
            work_mode=detect_work_mode(ubicacion, descripcion[:3000]),
            salary=parse_salary(descripcion),
            posted_at=publicada,
        )

    async def _read_ashby(self, empresa: dict, slug: str) -> list[JobOffer]:
        payload = await self.http.get_json(ASHBY_URL.format(slug=slug))
        nombre = empresa.get("name") or slug
        return [self._from_ashby(row, nombre, slug) for row in payload.get("jobs", [])]

    def _from_ashby(self, row: dict, nombre: str, slug: str) -> JobOffer:
        # Ashby reparte las ubicaciones entre la principal y las secundarias.
        ubicaciones = [row.get("location") or ""]
        ubicaciones += [
            (extra or {}).get("location", "") for extra in row.get("secondaryLocations") or []
        ]
        ubicacion = ", ".join(parte for parte in ubicaciones if parte)
        descripcion = clean_text(row.get("descriptionPlain") or row.get("descriptionHtml"))

        publicada = None
        if raw := row.get("publishedAt"):
            try:
                publicada = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
            except ValueError:
                publicada = None

        modo = WorkMode.REMOTE if row.get("isRemote") else detect_work_mode(ubicacion)
        return JobOffer(
            source=self.name,
            external_id=f"ashby:{slug}:{row.get('id')}",
            title=clean_text(row.get("title")),
            company=nombre,
            url=row.get("applyUrl") or row.get("jobUrl") or "",
            description=descripcion,
            location=ubicacion,
            work_mode=modo,
            salary=parse_salary(descripcion),
            posted_at=publicada,
        )
