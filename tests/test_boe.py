"""BOE adapter: fixture only, no network. Shapes mirror the real summary
endpoint, verified by hand against https://www.boe.es/datosabiertos/api/boe/
sumario/{AAAAMMDD} before writing this.
"""

from __future__ import annotations

from datetime import date

import pytest

from jobbot.adapters.public_sources.boe import BoeSource
from jobbot.domain.criteria import PublicCriteria
from jobbot.domain.public_models import Grupo, Turno

from .conftest import FakeHttp

FIXTURE_SUMARIO = {
    "data": {
        "sumario": {
            "diario": {
                "numero": "240",
                "seccion": [
                    {"codigo": "1", "nombre": "I. Disposiciones generales"},
                    {
                        "codigo": "2B",
                        "nombre": "II. Autoridades y personal. - B. Oposiciones y concursos",
                        "departamento": [
                            {
                                "codigo": "9999",
                                "nombre": "MINISTERIO DE HACIENDA",
                                "epigrafe": [
                                    {
                                        "nombre": (
                                            "Cuerpo Superior de Sistemas y Tecnologias "
                                            "de la Informacion"
                                        ),
                                        "item": {
                                            "identificador": "BOE-A-2026-10001",
                                            "titulo": (
                                                "Resolucion por la que se convoca proceso "
                                                "selectivo para ingreso, por el sistema "
                                                "general de acceso libre, en el Cuerpo "
                                                "Superior de Sistemas y Tecnologias de la "
                                                "Informacion, Grupo A2, de la Administracion "
                                                "del Estado. Plazo de presentacion de "
                                                "solicitudes: 20 dias habiles."
                                            ),
                                            "url_pdf": {"texto": "https://www.boe.es/x/1.pdf"},
                                            "url_html": "https://www.boe.es/x/1",
                                        },
                                    },
                                    {
                                        "nombre": (
                                            "Cuerpo Tecnico Auxiliar de Informatica, "
                                            "promocion interna"
                                        ),
                                        "item": {
                                            "identificador": "BOE-A-2026-10002",
                                            "titulo": (
                                                "Orden por la que se convoca, por el turno "
                                                "de promocion interna, proceso selectivo "
                                                "para el Cuerpo Tecnico Auxiliar de "
                                                "Informatica, Grupo C1."
                                            ),
                                            "url_pdf": {"texto": "https://www.boe.es/x/2.pdf"},
                                            "url_html": "https://www.boe.es/x/2",
                                        },
                                    },
                                    {
                                        "nombre": "Cuerpo de Letrados de la Administracion de "
                                        "Justicia",
                                        "item": {
                                            "identificador": "BOE-A-2026-10003",
                                            "titulo": (
                                                "Resolucion por la que se convoca proceso "
                                                "selectivo para el Cuerpo de Letrados de la "
                                                "Administracion de Justicia."
                                            ),
                                            "url_pdf": {"texto": "https://www.boe.es/x/3.pdf"},
                                            "url_html": "https://www.boe.es/x/3",
                                        },
                                    },
                                ],
                            }
                        ],
                    },
                ],
            }
        }
    }
}


@pytest.fixture
def criteria() -> PublicCriteria:
    return PublicCriteria()


@pytest.mark.asyncio
async def test_devuelve_solo_items_con_palabra_clave_tic(criteria):
    http = FakeHttp(json_payload=FIXTURE_SUMARIO)
    source = BoeSource(http, {})

    resultado = await source.search(criteria, on=date(2026, 10, 6))

    # El de Letrados de Justicia no lleva ninguna palabra clave TIC: fuera.
    identificadores = {o.identificador for o in resultado}
    assert "BOE-A-2026-10003" not in identificadores
    assert "BOE-A-2026-10001" in identificadores
    assert "BOE-A-2026-10002" in identificadores


@pytest.mark.asyncio
async def test_detecta_grupo_turno_y_plazo(criteria):
    http = FakeHttp(json_payload=FIXTURE_SUMARIO)
    source = BoeSource(http, {})

    resultado = await source.search(criteria, on=date(2026, 10, 6))
    libre = next(o for o in resultado if o.identificador == "BOE-A-2026-10001")

    assert libre.grupo == Grupo.A2
    assert libre.turno == Turno.LIBRE
    assert libre.plazo_dias_habiles == 20
    # 20 dias habiles desde el 6 de octubre de 2026 (martes): salta fines de
    # semana, asi que cae bastante mas tarde que +20 dias naturales.
    assert libre.fecha_limite_aproximada is not None
    assert libre.fecha_limite_aproximada > date(2026, 10, 26)


@pytest.mark.asyncio
async def test_a2_turno_libre_no_es_elegible_sin_grado(criteria):
    http = FakeHttp(json_payload=FIXTURE_SUMARIO)
    source = BoeSource(http, {})

    resultado = await source.search(criteria, on=date(2026, 10, 6))
    libre = next(o for o in resultado if o.identificador == "BOE-A-2026-10001")

    assert libre.elegible is False


@pytest.mark.asyncio
async def test_promocion_interna_se_detecta(criteria):
    http = FakeHttp(json_payload=FIXTURE_SUMARIO)
    source = BoeSource(http, {})

    resultado = await source.search(criteria, on=date(2026, 10, 6))
    interna = next(o for o in resultado if o.identificador == "BOE-A-2026-10002")

    assert interna.turno == Turno.PROMOCION_INTERNA


@pytest.mark.asyncio
async def test_un_dia_sin_sumario_no_rompe_la_busqueda(criteria):
    class BrokenHttp:
        async def get_json(self, url, **_kwargs):
            raise RuntimeError("404")

    source = BoeSource(BrokenHttp(), {})
    resultado = await source.safe_search(criteria, on=date(2026, 1, 1))

    assert resultado == []
