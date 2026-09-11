from __future__ import annotations

from jobbot.domain.fingerprint import fingerprint, normalize_company, url_key

from .conftest import make_offer


def test_misma_oferta_en_dos_portales_colapsa() -> None:
    linkedin = make_offer(
        source="linkedin",
        title="Senior Backend Engineer (Python) - Remoto",
        company="Acme Technologies S.L.",
        url="https://linkedin.com/jobs/view/123",
    )
    infojobs = make_offer(
        source="infojobs",
        title="Senior Backend Engineer (Python)",
        company="Acme Technologies",
        url="https://infojobs.net/of-i456",
    )
    assert fingerprint(linkedin) == fingerprint(infojobs)


def test_puestos_distintos_no_colapsan() -> None:
    backend = make_offer(title="Senior Backend Engineer")
    frontend = make_offer(title="Senior Frontend Engineer")
    assert fingerprint(backend) != fingerprint(frontend)


def test_empresas_distintas_no_colapsan() -> None:
    una = make_offer(company="Acme")
    otra = make_offer(company="Globex")
    assert fingerprint(una) != fingerprint(otra)


def test_sufijos_societarios_se_ignoran() -> None:
    assert normalize_company("Acme Technologies S.L.") == normalize_company("ACME technologies")


def test_url_key_ignora_parametros_de_tracking() -> None:
    limpia = url_key("https://example.com/jobs/1")
    sucia = url_key("https://example.com/jobs/1?utm_source=telegram&refId=abc")
    assert limpia == sucia
