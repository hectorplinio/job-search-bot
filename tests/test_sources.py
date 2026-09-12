"""Tests de los parsers, con fixtures copiados de la estructura real de cada
portal (septiembre 2026). Si un portal cambia el HTML, estos tests seguiran
verdes pero la fuente devolvera cero: por eso `jobbot run` avisa por fuente.
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
    assert offer.url == "https://es.linkedin.com/jobs/view/backend-developer-python-at-acme-4439920031"
    assert offer.work_mode is WorkMode.REMOTE
    # La tarjeta no trae salario; la ficha si.
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

    # La oferta de .NET no menciona ninguna tecnologia del perfil.
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
    """Concatenar y cortar hacia que la primera busqueda se llevara todo el
    cupo: asi es como se nos escapo una oferta que si estaba en LinkedIn."""
    from jobbot.adapters.sources.base import interleave

    primera = ["a1", "a2", "a3", "a4"]
    segunda = ["b1", "b2"]
    tercera = ["c1"]

    mezclado = interleave([primera, segunda, tercera])

    assert mezclado == ["a1", "b1", "c1", "a2", "b2", "a3", "a4"]
    # Con un tope de 3, antes solo entraba la primera busqueda. Ahora entran las tres.
    assert set(mezclado[:3]) == {"a1", "b1", "c1"}


def test_alternar_aguanta_listas_vacias() -> None:
    from jobbot.adapters.sources.base import interleave

    assert interleave([]) == []
    assert interleave([[], []]) == []
    assert interleave([[], ["b1"], []]) == ["b1"]


async def test_linkedin_pagina_hasta_agotar(criteria) -> None:
    """El endpoint de invitado sirve 10 por peticion. Sin paginar, el bot solo
    veia las diez primeras de cada busqueda."""
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

    # Pide la segunda pagina, y para al ver que viene incompleta.
    assert http.starts[:2] == ["0", "10"]
    assert "20" not in http.starts
    assert len(offers) == 11


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

    # Espana en la lista entra; lista vacia significa sin restriccion y tambien;
    # solo Estados Unidos se queda fuera.
    assert empresas == ["Remote Co", "Sin Limites"]
    assert (offers[0].salary.minimum, offers[0].salary.maximum) == (80_000, 110_000)


def test_elegibilidad_por_pais() -> None:
    from jobbot.adapters.sources.base import can_work_from

    assert can_work_from("Worldwide") is True
    assert can_work_from("") is True           # sin restriccion declarada
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
    # Aproximadamente la mitad de las ofertas no lo publican.
    assert leer("Hace 3 dias. Jornada completa.") is None
