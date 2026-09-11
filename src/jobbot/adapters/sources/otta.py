"""Otta, ahora dentro de Welcome to the Jungle.

Esta fuente va por navegador y no por HTTP, por dos razones comprobadas:

1. El sitio esta detras de AWS WAF con reto de JavaScript. Una peticion con
   `httpx` recibe un 202 con 2 KB y la cabecera `x-amzn-waf-action: challenge`.
   Copiar la cookie tampoco basta: hace falta un `aws-waf-token` que caduca en
   poco mas de una hora.
2. Otta no tiene listado de ofertas. Te ensena una y pasas a la siguiente con
   un boton. Hay que recorrerlas.

Y no usa las queries de config.yaml. Otta calcula tus "matches" a partir del
perfil que tengas en su web, asi que lo que afina esta fuente es ajustar tus
preferencias alli, no tocar nada aqui.

Requisitos:

    pip install -e ".[browser]"
    playwright install chromium
    jobbot login otta
"""

from __future__ import annotations

import logging

from ...domain.criteria import Criteria
from ...domain.models import JobOffer
from ...domain.salary import parse_salary
from .base import BaseSource, clean_text, detect_work_mode

logger = logging.getLogger(__name__)

JOBS_URL = "https://app.welcometothejungle.com/jobs"

# Otta marca su interfaz con data-testid, que aguanta los cambios de diseno
# mucho mejor que las clases CSS.
FIELD_TITLE = "job-title"
FIELD_SALARY = "salary-section"
FIELD_LOCATIONS = "job-locations"
FIELD_TECH = "job-technology-used"
FIELD_EXPERIENCE = "experience-section"
FIELD_BODY = "job-card-main"
NEXT_BUTTON = '[data-testid="next-button"]'

COOKIE_BANNER_LABELS = ("OK for me", "Aceptar todo", "No, thanks")


class OttaSource(BaseSource):
    name = "otta"

    async def search(self, criteria: Criteria) -> list[JobOffer]:
        from ..browser import BrowserSession, BrowserUnavailable

        profile = self.options.get("browser_profile")
        if not profile:
            logger.warning("Otta necesita el perfil del navegador; se omite.")
            return []

        limit = min(
            int(self.options.get("max_jobs", 20)),
            criteria.search.max_results_per_query,
        )
        collected: list[JobOffer] = []

        try:
            async with BrowserSession(profile, headless=True) as browser:
                page = await browser.open(JOBS_URL, wait_ms=9000)
                try:
                    await self._dismiss_cookie_banner(page)
                    if "/jobs" not in page.url:
                        logger.warning(
                            "Otta no abrio tus ofertas (acabo en %s). La sesion puede "
                            "haber caducado: ejecuta `jobbot login otta`.",
                            page.url,
                        )
                        return []

                    seen: set[str] = set()
                    for _ in range(limit):
                        offer = await self._read_current_job(page)
                        if offer is not None and offer.external_id not in seen:
                            seen.add(offer.external_id)
                            collected.append(offer)
                        if not await self._go_to_next(page):
                            break
                finally:
                    await page.close()
        except BrowserUnavailable as exc:
            logger.warning("Otta necesita el navegador: %s", exc)
            return []

        return collected

    @staticmethod
    async def _dismiss_cookie_banner(page) -> None:
        """El aviso de cookies tapa el boton de siguiente y corta el recorrido."""
        for label in COOKIE_BANNER_LABELS:
            try:
                await page.click(f'button:has-text("{label}")', timeout=2500)
                await page.wait_for_timeout(1200)
                return
            except Exception:  # noqa: BLE001 - si no sale el banner, mejor
                continue

    @staticmethod
    async def _field(page, testid: str) -> str:
        try:
            return await page.eval_on_selector(
                f'[data-testid="{testid}"]', "el => el.innerText.trim()"
            )
        except Exception:  # noqa: BLE001 - no todas las ofertas traen cada campo
            return ""

    async def _read_current_job(self, page) -> JobOffer | None:
        heading = await self._field(page, FIELD_TITLE)
        if not heading:
            return None

        # Otta mete puesto y empresa en el mismo campo: "Backend Engineer, Acme".
        title, _, company = heading.rpartition(",")
        if not title:
            title, company = heading, ""

        salary_text = await self._field(page, FIELD_SALARY)
        locations = await self._field(page, FIELD_LOCATIONS)
        technologies = await self._field(page, FIELD_TECH)
        experience = await self._field(page, FIELD_EXPERIENCE)
        body = await self._field(page, FIELD_BODY)

        # El nivel de experiencia entra en la descripcion a proposito: Otta
        # publica cosas como "Junior and Mid level", que el filtro de titulo no
        # ve pero el scoring si debe tener en cuenta.
        description = clean_text(
            " ".join(
                part.replace("\n", ", ")
                for part in (body, technologies, experience, locations)
                if part
            )
        )

        job_id = page.url.rstrip("/").rsplit("/", 1)[-1]
        return JobOffer(
            source=self.name,
            external_id=f"otta:{job_id}",
            title=title.strip(),
            company=company.strip(),
            url=page.url,
            description=description,
            location=locations.replace("\n", ", ") or None,
            work_mode=detect_work_mode(locations, description[:2000]),
            salary=parse_salary(salary_text, require_context=False),
        )

    @staticmethod
    async def _go_to_next(page) -> bool:
        previous_url = page.url
        try:
            await page.click(NEXT_BUTTON, timeout=5000)
        except Exception:  # noqa: BLE001 - se acabaron los matches
            return False

        await page.wait_for_timeout(4000)
        # Si la URL no cambia, no quedan mas ofertas por ver.
        return page.url != previous_url
