"""BOE (Boletín Oficial del Estado), via its open-data API.

No key needed. One request per day gets you the whole day's summary, section
"II.B - Oposiciones y concursos" included, which is exactly where TIC
vacancies for the Estado get published.

Known limitation, honestly stated rather than hidden: section II.B mixes
genuine new openings ("se convoca proceso selectivo...") with procedural
updates about processes already running (admitted/excluded lists, exam
dates, corrections). This adapter does not try to tell them apart by legal
phrasing - it surfaces every matching item, title and deadline included, and
the "días hábiles" detection naturally comes up empty on updates that are not
a fresh call, which already pushes those down in the score. Telling a true
opening from an update with certainty would need parsing the legal boilerplate
properly; left for a later pass if the noise turns out to matter in practice.
"""

from __future__ import annotations

import logging
from datetime import date

from ...domain.criteria import PublicCriteria
from ...domain.public_models import Ambito, Grupo, Oposicion, TipoPlaza, Turno
from ...domain.public_scoring import (
    business_days_after,
    contains,
    detect_grupo,
    detect_plazo_dias,
    detect_tipo_plaza,
    detect_turno,
)
from .base import PublicBaseSource

logger = logging.getLogger(__name__)

SUMARIO_URL = "https://www.boe.es/datosabiertos/api/boe/sumario/{fecha}"
SECCION_OPOSICIONES = "2B"


def _as_list(value: object) -> list:
    """The BOE API gives you a dict when there is exactly one, a list
    otherwise. Every call site needs a list."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


class BoeSource(PublicBaseSource):
    name = "boe"

    async def search(self, criteria: PublicCriteria, *, on: date | None = None) -> list[Oposicion]:
        fecha = on or date.today()
        url = SUMARIO_URL.format(fecha=fecha.strftime("%Y%m%d"))
        try:
            payload = await self.http.get_json(url)
        except Exception:
            logger.info("BOE: no summary for %s (holiday, or not published yet)", fecha)
            return []

        sumario = (payload or {}).get("data", {}).get("sumario", {})
        diarios = _as_list(sumario.get("diario"))
        items: list[Oposicion] = []
        for diario in diarios:
            for seccion in _as_list(diario.get("seccion")):
                if seccion.get("codigo") != SECCION_OPOSICIONES:
                    continue
                items.extend(self._from_seccion(seccion, criteria, fecha))
        return items

    def _from_seccion(
        self, seccion: dict, criteria: PublicCriteria, fecha: date
    ) -> list[Oposicion]:
        results: list[Oposicion] = []
        for departamento in _as_list(seccion.get("departamento")):
            organismo = departamento.get("nombre", "").strip()
            for epigrafe in _as_list(departamento.get("epigrafe")):
                cuerpo = epigrafe.get("nombre", "").strip()
                for item in _as_list(epigrafe.get("item")):
                    oposicion = self._to_oposicion(item, organismo, cuerpo, fecha, criteria)
                    if oposicion is not None:
                        results.append(oposicion)
        return results

    def _to_oposicion(
        self, item: dict, organismo: str, cuerpo: str, fecha: date, criteria: PublicCriteria
    ) -> Oposicion | None:
        titulo = (item.get("titulo") or "").strip()
        identificador = item.get("identificador") or ""
        if not titulo or not identificador:
            return None

        # Title-level filter before doing anything else with this item - same
        # principle as title_blockers() on the private side: cheap to check,
        # saves the rest of the work for what might actually matter.
        haystack = f"{titulo} {cuerpo}"
        if not any(contains(haystack, kw) for kw in criteria.keywords):
            return None

        url_html = (item.get("url_html") or "").strip()
        url_pdf = ((item.get("url_pdf") or {}).get("texto") or "").strip()
        url = url_html or url_pdf

        grupo_raw = detect_grupo(haystack)
        grupo = Grupo(grupo_raw) if grupo_raw else Grupo.DESCONOCIDO

        turno = detect_turno(haystack)
        tipo_raw = detect_tipo_plaza(haystack)
        tipo_plaza = (
            TipoPlaza(tipo_raw)
            if tipo_raw
            else (TipoPlaza.FIJA if turno != Turno.DESCONOCIDO else TipoPlaza.DESCONOCIDO)
        )

        plazo = detect_plazo_dias(haystack) or criteria.default_plazo_dias_habiles
        fecha_limite = business_days_after(fecha, plazo)

        return Oposicion(
            fuente=self.name,
            identificador=identificador,
            titulo=titulo,
            organismo=organismo,
            url=url,
            fecha_publicacion=fecha,
            ambito=Ambito.ESTADO,
            grupo=grupo,
            turno=turno,
            tipo_plaza=tipo_plaza,
            plazo_dias_habiles=plazo,
            fecha_limite_aproximada=fecha_limite,
            cuerpo=cuerpo,
        )
