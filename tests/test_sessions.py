"""Las cookies de sesion son secretos: estos tests fijan que solo salen hacia
la fuente a la que pertenecen y que sin cookie no se manda nada."""

from __future__ import annotations

from jobbot.adapters.sources.infojobs import InfoJobsSource
from jobbot.adapters.sources.registry import build_sources
from jobbot.settings import Settings

from .conftest import FakeHttp

INFOJOBS_CARD = """
<div class="ij-OfferCardContent-description">
  <h2><a class="ij-OfferCardContent-description-link"
         href="//www.infojobs.net/madrid/backend-python/of-iabc123"
         aria-label="Backend Python">Backend Python</a></h2>
  <h3><a class="ij-OfferCardContent-description-subtitle-link" href="#">Acme</a></h3>
  <ul class="ij-OfferCardContent-description-list">
    <li class="ij-OfferCardContent-description-list-item">Madrid</li>
    <li class="ij-OfferCardContent-description-list-item">Teletrabajo</li>
  </ul>
  <p class="ij-OfferCardContent-description-description">Python, AWS y PostgreSQL.</p>
</div>
"""


class RecordingHttp(FakeHttp):
    """Guarda las cabeceras de cada peticion para poder inspeccionarlas."""

    def __init__(self, body: str) -> None:
        super().__init__({"": body})
        self.headers_sent: list[dict] = []

    async def get_text(self, url: str, **kwargs) -> str:
        self.headers_sent.append(kwargs.get("headers") or {})
        return await super().get_text(url, **kwargs)


async def test_sin_cookie_no_manda_cabecera_de_sesion(criteria) -> None:
    http = RecordingHttp(INFOJOBS_CARD)
    source = InfoJobsSource(http, {})

    assert source.has_session is False
    await source.search(criteria)

    assert all("Cookie" not in headers for headers in http.headers_sent)


async def test_con_cookie_la_manda_y_parece_un_navegador(criteria) -> None:
    http = RecordingHttp(INFOJOBS_CARD)
    source = InfoJobsSource(http, {"cookie": "sid=secreto123"})

    assert source.has_session is True
    await source.search(criteria)

    assert http.headers_sent, "la fuente no llego a pedir nada"
    first = http.headers_sent[0]
    assert first["Cookie"] == "sid=secreto123"
    # Una peticion con sesion pero sin cabeceras de navegador canta demasiado.
    assert first["Sec-Fetch-Mode"] == "navigate"


def test_la_cookie_solo_llega_a_su_fuente(criteria) -> None:
    """Un fallo aqui filtraria tu sesion de InfoJobs a LinkedIn."""
    cookies = {"infojobs": "sid=solo-infojobs"}
    sources = build_sources(FakeHttp(), criteria, cookies)

    con_sesion = [source.name for source in sources if source.has_session]
    assert con_sesion == ["infojobs"]

    for source in sources:
        if source.name != "infojobs":
            assert "Cookie" not in source.auth_headers()


def test_las_cookies_se_leen_del_entorno(monkeypatch) -> None:
    # Las cuatro explicitas: si el .env real del usuario trae alguna, este
    # test no debe depender de ella.
    monkeypatch.setenv("INFOJOBS_COOKIE", "  sid=abc  ")
    monkeypatch.setenv("GLASSDOOR_COOKIE", "")
    monkeypatch.setenv("LINKEDIN_COOKIE", "")
    monkeypatch.setenv("OTTA_COOKIE", "")

    settings = Settings.from_env()

    # Una variable vacia no cuenta como sesion.
    assert settings.source_cookies == {"infojobs": "sid=abc"}


def test_config_yaml_no_lleva_cookies() -> None:
    """Las cookies van en .env, que esta en .gitignore. config.yaml se comparte."""
    from jobbot.settings import PROJECT_ROOT

    raw = (PROJECT_ROOT / "config.yaml").read_text(encoding="utf-8").lower()
    assert "cookie:" not in raw
