"""HN "Who is hiring?": fixture only, no network. Shapes mirror a real
response from hn.algolia.com, checked by hand before writing this."""

from __future__ import annotations

import pytest

from jobbot.adapters.sources.hn_whoishiring import HackerNewsSource
from jobbot.domain.models import WorkMode
from jobbot.domain.scoring import score_offer

# `criteria` is a fixture, picked up automatically from conftest.py - every
# other test module in this package uses it the same way, with no import.


class FakeHnHttp:
    """Answers the two HN Algolia endpoints the adapter calls, by URL."""

    def __init__(self, search_payload: dict, item_payload: dict) -> None:
        self.search_payload = search_payload
        self.item_payload = item_payload
        self.calls: list[str] = []

    async def get_json(self, url: str, **kwargs):
        self.calls.append(url)
        if "search_by_date" in url:
            return self.search_payload
        return self.item_payload


SEARCH_PAYLOAD = {
    "hits": [
        {"objectID": "999", "title": "Ask HN: Who wants to be hired? (October 2026)"},
        {"objectID": "123", "title": "Ask HN: Who is hiring? (October 2026)"},
        {"objectID": "100", "title": "Ask HN: Who is hiring? (September 2026)"},
    ]
}

ITEM_PAYLOAD = {
    "id": 123,
    "children": [
        {
            "id": 201,
            "text": (
                "Acme Corp | Senior Backend Engineer | Remote (Europe) | Full-time"
                "<p>We build payment infrastructure in Python and Go."
                "<p>Apply: jobs@acme.example"
            ),
        },
        {
            "id": 202,
            "text": (
                "Foo Inc | Backend Engineer | Onsite New York, US Only"
                "<p>Python shop, on-site only, US work authorization required."
            ),
        },
        {
            "id": 203,
            "text": "Bar Studio | Unity Game Designer | Remote (Worldwide)"
            "<p>No programming involved, pure design role.",
        },
        {
            "id": 205,
            "text": (
                "Voygr | Founding Backend Engineer | San Francisco | ONSITE | Full-time"
                "<p>We build Python infrastructure, in office five days a week."
            ),
        },
        {"id": 204, "text": None},  # dead/deleted comment
    ],
}


@pytest.fixture
def hn_http() -> FakeHnHttp:
    return FakeHnHttp(SEARCH_PAYLOAD, ITEM_PAYLOAD)


@pytest.mark.asyncio
async def test_elige_el_hilo_who_is_hiring_no_el_de_who_wants_to_be_hired(hn_http, criteria):
    source = HackerNewsSource(hn_http, {})

    await source.search(criteria)

    assert any("items/123" in call for call in hn_http.calls)
    assert not any("items/999" in call for call in hn_http.calls)


@pytest.mark.asyncio
async def test_separa_empresa_y_puesto_cuando_sigue_el_formato_con_barras(hn_http, criteria):
    source = HackerNewsSource(hn_http, {})

    offers = await source.search(criteria)
    acme = next(o for o in offers if o.external_id == "hn:201")

    assert acme.company == "Acme Corp"
    assert "Senior Backend Engineer" in acme.title
    assert acme.work_mode == WorkMode.REMOTE


@pytest.mark.asyncio
async def test_el_filtro_de_region_no_es_cosa_del_adapter(hn_http, criteria):
    """ "US Only" no se descarta aqui: la mayoria de posts de HN no dicen
    region en absoluto, y rechazar todo lo que no la menciona tiraria buenas
    ofertas. Ese filtro vive en el bloqueo compartido (exclude.description),
    que se aplica en el scoring, no en cada adapter por separado."""
    source = HackerNewsSource(hn_http, {})

    offers = await source.search(criteria)

    foo = next(o for o in offers if o.external_id == "hn:202")
    assert "us only" in foo.searchable_text


@pytest.mark.asyncio
async def test_descarta_lo_que_no_coincide_con_el_stack(hn_http, criteria):
    source = HackerNewsSource(hn_http, {})

    offers = await source.search(criteria)

    assert not any(o.external_id == "hn:203" for o in offers)


@pytest.mark.asyncio
async def test_onsite_se_detecta_y_no_pasa_como_remoto(hn_http, criteria):
    """Regresion real: el primer intento solo distinguia REMOTE de UNKNOWN,
    asi que un puesto 'ONSITE | San Francisco' caia en UNKNOWN y pasaba el
    filtro de work_mode (que acepta remote y unknown), coloandose entre las
    alertas. Debe quedar marcado ONSITE y el filtro debe descartarlo."""
    source = HackerNewsSource(hn_http, {})

    offers = await source.search(criteria)
    voygr = next(o for o in offers if o.external_id == "hn:205")

    assert voygr.work_mode == WorkMode.ONSITE

    # criteria aqui es la config real: work_mode.rejected incluye "onsite".
    score = score_offer(voygr, criteria)
    assert score.is_rejected is True
    assert any("onsite" in blocker for blocker in score.blockers)


@pytest.mark.asyncio
async def test_comentarios_borrados_no_rompen_la_busqueda(hn_http, criteria):
    source = HackerNewsSource(hn_http, {})

    offers = await source.search(criteria)

    assert not any(o.external_id == "hn:204" for o in offers)
