"""Parser tests, with fixtures copied from the real structure of each job
board (September 2026). If a board changes its HTML these tests stay green but
the source returns zero: that is why `jobbot run` warns per source.
"""

from __future__ import annotations

import json

from jobbot.adapters.sources.infojobs import InfoJobsSource
from jobbot.adapters.sources.linkedin import LinkedInSource
from jobbot.adapters.sources.manfred import ManfredSource
from jobbot.adapters.sources.remoteok import RemoteOkSource
from jobbot.adapters.sources.tecnoempleo import TecnoempleoSource
from jobbot.domain.models import WorkMode

from .conftest import FakeHttp

LINKEDIN_CARD = """
<ul>
<li>
  <div class="base-card job-search-card" data-entity-urn="urn:li:jobPosting:4439920031">
    <a class="base-card__full-link" href="https://es.linkedin.com/jobs/view/backend-developer-python-at-acme-4439920031?position=1">
      <span class="sr-only">Backend Developer (Python)</span>
    </a>
    <div class="base-search-card__info">
      <h3 class="base-search-card__title">Backend Developer (Python)</h3>
      <h4 class="base-search-card__subtitle"><a href="#">Acme Logistics</a></h4>
      <div class="base-search-card__metadata">
        <span class="job-search-card__location">Barcelona (Remoto)</span>
        <time class="job-search-card__listdate" datetime="2026-09-08">hace 2 días</time>
      </div>
    </div>
  </div>
</li>
</ul>
"""

LINKEDIN_DETAIL = """
<div class="show-more-less-html__markup">
  Buscamos Senior Backend con Python, FastAPI, PostgreSQL, Kubernetes y AWS.
  Salario: 55.000€ - 70.000€ brutos anuales.
</div>
<ul><li class="description__job-criteria-item">Nivel: Intermedio</li></ul>
"""

TECNOEMPLEO_CARD = """
<div class="col-12">
  <div class="p-3 border rounded mb-3 bg-white">
    <div class="row fs--15">
      <div class="col-10">
        <h3 class="fs-5 mb-2">
          <a href="https://www.tecnoempleo.com/senior-python-developer-acme/python/rf-f8de12f5c2daa375aa42"
             class="font-weight-bold" title="Senior Python Developer">Senior Python Developer</a>
        </h3>
        <a href="/acme-trabajo" class="text-primary link-muted">Acme</a>
        <span class="hidden-md-down text-gray-800">
          Modalidad: 100% remoto. Salario: 50000 a 60000 brutos anuales. Stack Python, PostgreSQL, AWS.
          <span class="badge bg-danger text-white mx-1">Python</span>
          <span class="badge bg-gray-500 mx-1">AWS</span>
        </span>
      </div>
      <div class="col-12 col-lg-3 text-right">
        <span>10/09/2026<br><b>Madrid</b> (Teletrabajo)<br>Programador</span>
      </div>
    </div>
  </div>
</div>
"""

INFOJOBS_CARD = """
<div class="ij-OfferCardContent-info"><div class="ij-OfferCardContent-description">
  <h2><a class="ij-OfferCardContent-description-link"
         href="//www.infojobs.net/madrid/tech-lead-python/of-i1f23a455c44b5087b65774dc3b26c7?applicationOrigin=search"
         aria-label="Tech Lead (Python)"><span>Tech Lead (Python)</span></a></h2>
  <h3><a class="ij-OfferCardContent-description-subtitle-link" href="#">SABIA Personal</a></h3>
  <ul class="ij-OfferCardContent-description-list">
    <li class="ij-OfferCardContent-description-list-item">Madrid</li>
    <li class="ij-OfferCardContent-description-list-item">Híbrido</li>
    <li class="ij-OfferCardContent-description-list-item">Hace 1d</li>
    <li class="ij-OfferCardContent-description-list-item">
      <span class="ij-OfferCardContent-description-salary-info">50.000 €<!-- --> - <!-- -->56.000 €<!-- --> Bruto/año</span>
    </li>
  </ul>
  <p class="ij-OfferCardContent-description-description">
    Buscamos un Tech Lead con mas de 5 años en Python liderando equipos.
  </p>
</div></div>
"""

MANFRED_LIST = [
    {
        "id": 8451,
        "position": "Senior Python Engineer",
        "slug": "acme-senior-python-engineer",
        "status": "ACTIVE",
        "salaryFrom": 50000,
        "salaryTo": 60000,
        "remotePercentage": 100,
        "currency": "€",
        "locations": [],
        "highlights": ["🤖 IA", "🌎 Remoto 100%"],
        "updatedAt": "2026-09-10T09:46:47.680Z",
        "company": {"name": "Acme"},
    },
    {
        "id": 8457,
        "position": ".NET Developer",
        "slug": "otra-net-developer",
        "status": "ACTIVE",
        "salaryFrom": 0,
        "salaryTo": 35000,
        "remotePercentage": 40,
        "currency": "€",
        "locations": ["Santander, España"],
        "highlights": [],
        "updatedAt": "2026-09-04T20:18:07.614Z",
        "company": {"name": "Otra"},
    },
]

MANFRED_DETAIL = (
    '<script id="__NEXT_DATA__" type="application/json">'
    + json.dumps(
        {
            "props": {
                "pageProps": {
                    "offer": {
                        "jsonld": json.dumps(
                            {
                                "@type": "JobPosting",
                                "description": "Python, FastAPI, PostgreSQL, Kubernetes y AWS.",
                            }
                        )
                    }
                }
            }
        }
    )
    + "</script>"
)


async def test_linkedin_parsea_tarjeta_y_ficha(criteria) -> None:
    http = FakeHttp(
        {
            "seeMoreJobPostings": LINKEDIN_CARD,
            "jobPosting/4439920031": LINKEDIN_DETAIL,
        }
    )
    source = LinkedInSource(http, {})
    offers = await source.search(criteria)

    assert len(offers) == 1
    offer = offers[0]
    assert offer.title == "Backend Developer (Python)"
    assert offer.company == "Acme Logistics"
    assert offer.external_id == "linkedin:4439920031"
    assert (
        offer.url == "https://es.linkedin.com/jobs/view/backend-developer-python-at-acme-4439920031"
    )
    assert offer.work_mode is WorkMode.REMOTE
    # The card carries no salary; the detail page does.
    assert offer.salary.minimum == 55_000
    assert "FastAPI" in offer.description


async def test_tecnoempleo_parsea_modalidad_y_salario(criteria) -> None:
    source = TecnoempleoSource(FakeHttp({"tecnoempleo.com": TECNOEMPLEO_CARD}), {})
    offers = await source.search(criteria)

    assert len(offers) == 1
    offer = offers[0]
    assert offer.title == "Senior Python Developer"
    assert offer.company == "Acme"
    assert offer.work_mode is WorkMode.REMOTE
    assert (offer.salary.minimum, offer.salary.maximum) == (50_000, 60_000)
    assert "Python" in offer.tags


async def test_infojobs_parsea_salario_partido_por_comentarios(criteria) -> None:
    source = InfoJobsSource(FakeHttp({"infojobs.net": INFOJOBS_CARD}), {})
    offers = await source.search(criteria)

    assert len(offers) == 1
    offer = offers[0]
    assert offer.title == "Tech Lead (Python)"
    assert offer.company == "SABIA Personal"
    assert offer.external_id == "infojobs:1f23a455c44b5087b65774dc3b26c7"
    assert offer.work_mode is WorkMode.HYBRID
    assert (offer.salary.minimum, offer.salary.maximum) == (50_000, 56_000)
    assert "?" not in offer.url


async def test_manfred_filtra_por_stack_y_enriquece(criteria) -> None:
    http = FakeHttp({"getmanfred.com/ofertas-empleo": MANFRED_DETAIL}, json_payload=MANFRED_LIST)
    source = ManfredSource(http, {})
    offers = await source.search(criteria)

    # The .NET posting mentions no technology from the profile.
    assert [offer.title for offer in offers] == ["Senior Python Engineer"]
    offer = offers[0]
    assert offer.work_mode is WorkMode.REMOTE
    assert (offer.salary.minimum, offer.salary.maximum) == (50_000, 60_000)
    assert "Kubernetes" in offer.description


async def test_remoteok_ignora_el_aviso_legal(criteria) -> None:
    payload = [
        {"legal": "RemoteOK legal notice"},
        {
            "id": "12345",
            "position": "Senior Python Engineer",
            "company": "Remote Co",
            "url": "https://remoteok.com/remote-jobs/12345",
            "description": "Python, PostgreSQL, AWS, microservices.",
            "tags": ["python", "aws"],
            "location": "Worldwide",
            "salary_min": 90000,
            "salary_max": 120000,
            "date": "2026-09-09T10:00:00+00:00",
        },
    ]
    source = RemoteOkSource(FakeHttp(json_payload=payload), {})
    offers = await source.search(criteria)

    assert len(offers) == 1
    assert offers[0].salary.currency == "USD"
    assert offers[0].work_mode is WorkMode.REMOTE


def test_alternar_reparte_el_cupo_entre_busquedas() -> None:
    """Concatenating and truncating let the first search take the whole quota:
    that is how a posting that was on LinkedIn got away from us."""
    from jobbot.adapters.sources.base import interleave

    primera = ["a1", "a2", "a3", "a4"]
    segunda = ["b1", "b2"]
    tercera = ["c1"]

    mezclado = interleave([primera, segunda, tercera])

    assert mezclado == ["a1", "b1", "c1", "a2", "b2", "a3", "a4"]
    # With a cap of 3, only the first search used to get in. Now all three do.
    assert set(mezclado[:3]) == {"a1", "b1", "c1"}


def test_alternar_aguanta_listas_vacias() -> None:
    from jobbot.adapters.sources.base import interleave

    assert interleave([]) == []
    assert interleave([[], []]) == []
    assert interleave([[], ["b1"], []]) == ["b1"]


async def test_linkedin_pagina_hasta_agotar(criteria) -> None:
    """The guest endpoint serves 10 per request. Without pagination the bot
    only saw the first ten of each search."""
    pagina_llena = "".join(
        LINKEDIN_CARD.replace("4439920031", str(4439920000 + n)) for n in range(10)
    )
    pagina_corta = LINKEDIN_CARD.replace("4439920031", "4439999999")

    class HttpPaginado(FakeHttp):
        def __init__(self) -> None:
            super().__init__({})
            self.starts: list[str] = []

        async def get_text(self, url: str, **kwargs) -> str:
            if "seeMoreJobPostings" in url:
                start = str((kwargs.get("params") or {}).get("start", 0))
                self.starts.append(start)
                return pagina_llena if start == "0" else pagina_corta
            return LINKEDIN_DETAIL

    http = HttpPaginado()
    criteria.search.queries = ["python"]
    criteria.search.locations = ["Spain"]
    offers = await LinkedInSource(http, {"pages": 3}).search(criteria)

    # It asks for the second page, and stops when it comes back incomplete.
    assert http.starts[:2] == ["0", "10"]
    assert "20" not in http.starts
    assert len(offers) == 11


async def test_linkedin_tiene_su_propio_tope(criteria) -> None:
    """The shared cap of 40 threw away most of what LinkedIn has: measured, the
    configured searches return over 400 unique postings. Its own cap lives in
    the source options."""

    class HttpLleno(FakeHttp):
        def __init__(self) -> None:
            super().__init__({})
            self.fichas = 0

        async def get_text(self, url: str, **kwargs) -> str:
            if "seeMoreJobPostings" in url:
                start = int((kwargs.get("params") or {}).get("start", 0))
                return "".join(
                    LINKEDIN_CARD.replace("4439920031", str(4439920000 + start + n))
                    for n in range(10)
                )
            self.fichas += 1
            return LINKEDIN_DETAIL

    criteria.search.queries = ["python"]
    criteria.search.locations = ["Spain"]
    criteria.search.max_results_per_query = 50
    criteria.search.max_results_per_source = 40

    http = HttpLleno()
    offers = await LinkedInSource(http, {"pages": 5, "max_results": 35}).search(criteria)
    assert len(offers) == 35
    # One request per description: that is what the cap is really limiting.
    assert http.fichas == 35

    # Without the override it falls back to the shared cap.
    http = HttpLleno()
    offers = await LinkedInSource(http, {"pages": 5}).search(criteria)
    assert len(offers) == 40


async def test_linkedin_descarta_por_titulo_antes_de_pedir_la_ficha(criteria) -> None:
    """Every description is one extra request, so a title that is already
    rejected must not cost one."""
    tarjetas = LINKEDIN_CARD + LINKEDIN_CARD.replace("4439920031", "4439920099").replace(
        "Backend Developer (Python)", "Junior Frontend Developer"
    )

    class HttpDos(FakeHttp):
        def __init__(self) -> None:
            super().__init__({})
            self.fichas = 0

        async def get_text(self, url: str, **kwargs) -> str:
            if "seeMoreJobPostings" in url:
                return tarjetas
            self.fichas += 1
            return LINKEDIN_DETAIL

    criteria.search.queries = ["python"]
    criteria.search.locations = ["Spain"]

    http = HttpDos()
    offers = await LinkedInSource(http, {"pages": 1}).search(criteria)

    assert len(offers) == 1
    assert http.fichas == 1


REMOTIVE_PAYLOAD = {
    "jobs": [
        {
            "id": 1,
            "title": "Senior Backend Engineer (Python)",
            "company_name": "Acme US",
            "url": "https://remotive.com/remote-jobs/software-dev/senior-backend-1",
            "description": "Python, PostgreSQL, AWS and Kubernetes.",
            "tags": ["python", "aws"],
            "candidate_required_location": "LATAM, Europe, USA, Canada",
            "salary": "$90,000 - $120,000",
            "publication_date": "2026-09-10T08:00:00",
        },
        {
            "id": 2,
            "title": "Backend Engineer (Python)",
            "company_name": "Solo Yanquis",
            "url": "https://remotive.com/remote-jobs/software-dev/solo-2",
            "description": "Python and Django.",
            "tags": ["python"],
            "candidate_required_location": "USA",
            "salary": "",
            "publication_date": "2026-09-11T08:00:00",
        },
    ]
}

HIMALAYAS_PAYLOAD = {
    "jobs": [
        {
            "guid": "abc",
            "title": "Senior Backend Engineer",
            "companyName": "Remote Co",
            "applicationLink": "https://himalayas.app/companies/remote-co/jobs/senior-backend",
            "description": "Python, PostgreSQL, Kubernetes, event-driven microservices.",
            "excerpt": "Backend role",
            "categories": ["Backend"],
            "locationRestrictions": ["Spain", "Portugal", "France"],
            "minSalary": 80000,
            "maxSalary": 110000,
            "currency": "EUR",
        },
        {
            "guid": "def",
            "title": "Backend Engineer (Python)",
            "companyName": "US Only Inc",
            "applicationLink": "https://himalayas.app/x",
            "description": "Python and AWS.",
            "categories": ["Backend"],
            "locationRestrictions": ["United States"],
        },
        {
            "guid": "ghi",
            "title": "Python Platform Engineer",
            "companyName": "Sin Limites",
            "applicationLink": "https://himalayas.app/y",
            "description": "Python, Kubernetes and PostgreSQL.",
            "categories": ["Backend"],
            "locationRestrictions": [],
        },
    ]
}


async def test_remotive_descarta_lo_que_es_solo_para_eeuu(criteria) -> None:
    from jobbot.adapters.sources.remotive import RemotiveSource

    offers = await RemotiveSource(FakeHttp(json_payload=REMOTIVE_PAYLOAD), {}).search(criteria)

    assert [o.company for o in offers] == ["Acme US"]
    offer = offers[0]
    assert offer.work_mode is WorkMode.REMOTE
    assert (offer.salary.minimum, offer.salary.maximum) == (90_000, 120_000)
    assert offer.salary.currency == "USD"


async def test_himalayas_usa_la_lista_de_paises(criteria) -> None:
    from jobbot.adapters.sources.himalayas import HimalayasSource

    offers = await HimalayasSource(FakeHttp(json_payload=HIMALAYAS_PAYLOAD), {}).search(criteria)
    empresas = [o.company for o in offers]

    # Spain on the list gets in; an empty list means no restriction and also
    # gets in; United States only stays out.
    assert empresas == ["Remote Co", "Sin Limites"]
    assert (offers[0].salary.minimum, offers[0].salary.maximum) == (80_000, 110_000)


def test_elegibilidad_por_pais() -> None:
    from jobbot.adapters.sources.base import can_work_from

    assert can_work_from("Worldwide") is True
    assert can_work_from("") is True  # no restriction declared
    assert can_work_from("Europe") is True
    assert can_work_from("LATAM, Europe, USA") is True
    assert can_work_from("Spain, Portugal") is True
    assert can_work_from("USA") is False
    assert can_work_from("United States") is False
    assert can_work_from("USA, Canada, USA timezones") is False


def test_linkedin_lee_cuantos_han_solicitado() -> None:
    from jobbot.adapters.sources.linkedin import LinkedInSource

    leer = LinkedInSource._parse_applicants
    assert leer("Hace 7 horas  Más de 200 solicitudes  Descubre") == 200
    assert leer("hace 2 horas · 6 solicitudes") == 6
    assert leer("Over 150 applicants") == 150
    assert leer("1.200 solicitudes") == 1200
    # Roughly half the postings do not publish it.
    assert leer("Hace 3 dias. Jornada completa.") is None
