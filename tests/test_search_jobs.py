from __future__ import annotations

from jobbot.adapters.persistence import SqliteOfferRepository
from jobbot.application.search_jobs import SearchJobs
from jobbot.domain.models import MatchScore, SalaryRange, WorkMode

from .conftest import make_offer


class FakeSource:
    def __init__(self, name: str, offers: list) -> None:
        self.name = name
        self._offers = offers

    async def safe_search(self, _criteria):
        return self._offers


class FakeNotifier:
    def __init__(self) -> None:
        self.sent = []

    async def send_offer(self, scored) -> None:
        self.sent.append(scored)

    async def send_text(self, text: str) -> None:
        self.sent.append(text)


class FakeWriter:
    """Devuelve siempre un 9 para comprobar que la nota del LLM manda."""

    def __init__(self) -> None:
        self.calls = 0

    async def rate(self, candidates, _profile, *, salary_minimum, salary_target):
        self.calls += 1
        return [
            (MatchScore(value=9, reasons=("python", "remoto"), source_of_truth="llm"),
             "Backend Python remoto con el stack que ya usas.")
            for _ in candidates
        ]


def build(tmp_path, sources, criteria, profile, writer=None):
    repository = SqliteOfferRepository(tmp_path / "test.sqlite3")
    notifier = FakeNotifier()
    use_case = SearchJobs(
        sources=sources,
        repository=repository,
        notifier=notifier,
        criteria=criteria,
        profile=profile,
        writer=writer,
    )
    return use_case, repository, notifier


async def test_manda_la_oferta_buena_y_descarta_la_mala(tmp_path, criteria, profile) -> None:
    buena = make_offer(external_id="a", url="https://example.com/a")
    mala = make_offer(
        external_id="b",
        url="https://example.com/b",
        title="Junior Python Developer",
        company="Otra",
    )
    use_case, repository, notifier = build(
        tmp_path, [FakeSource("fake", [buena, mala])], criteria, profile
    )

    report = await use_case.run()

    assert report.fetched == 2
    assert report.rejected == 1
    assert report.notified == 1
    assert notifier.sent[0].offer.url == "https://example.com/a"
    repository.close()


async def test_no_repite_la_misma_oferta_en_dos_ejecuciones(tmp_path, criteria, profile) -> None:
    offer = make_offer()
    use_case, repository, notifier = build(
        tmp_path, [FakeSource("fake", [offer])], criteria, profile
    )

    primera = await use_case.run()
    segunda = await use_case.run()

    assert primera.notified == 1
    assert segunda.notified == 0
    assert segunda.duplicates == 1
    assert len(notifier.sent) == 1
    repository.close()


async def test_deduplica_entre_fuentes_en_la_misma_pasada(tmp_path, criteria, profile) -> None:
    en_linkedin = make_offer(
        source="linkedin", external_id="li:1", url="https://linkedin.com/jobs/view/1"
    )
    en_infojobs = make_offer(
        source="infojobs",
        external_id="ij:1",
        url="https://infojobs.net/of-i1",
        title="Senior Backend Engineer (Python) - Remoto",
    )
    use_case, repository, notifier = build(
        tmp_path,
        [FakeSource("linkedin", [en_linkedin]), FakeSource("infojobs", [en_infojobs])],
        criteria,
        profile,
    )

    report = await use_case.run()

    assert report.fetched == 2
    assert report.duplicates == 1
    assert report.notified == 1
    repository.close()


async def test_dry_run_no_manda_nada(tmp_path, criteria, profile) -> None:
    use_case, repository, notifier = build(
        tmp_path, [FakeSource("fake", [make_offer()])], criteria, profile
    )

    report = await use_case.run(dry_run=True)

    assert report.alerts and report.notified == 0
    assert notifier.sent == []
    repository.close()


async def test_dry_run_no_deja_rastro_en_el_historial(tmp_path, criteria, profile) -> None:
    """Un ensayo que guardase daria las ofertas por vistas, y la siguiente
    ejecucion de verdad no te mandaria ninguna."""
    buena = make_offer(external_id="a", url="https://example.com/a")
    descartada = make_offer(
        external_id="b", url="https://example.com/b", title="Junior Python Developer"
    )
    source = FakeSource("fake", [buena, descartada])

    use_case, repository, notifier = build(tmp_path, [source], criteria, profile)
    await use_case.run(dry_run=True)

    # Ni las buenas ni las descartadas: el historial sigue vacio.
    assert repository.stats()["vistas"] == 0

    # Y la ejecucion real que viene detras si te las manda.
    real, _repo, real_notifier = build(tmp_path, [source], criteria, profile)
    real._repository = repository
    report = await real.run()

    assert report.notified == 1
    assert real_notifier.sent[0].offer.url == "https://example.com/a"
    repository.close()


async def test_el_llm_reemplaza_la_nota_de_reglas(tmp_path, criteria, profile) -> None:
    # Una oferta sin salario ni modalidad saca menos por reglas; el LLM la sube.
    offer = make_offer(salary=SalaryRange(), work_mode=WorkMode.UNKNOWN)
    writer = FakeWriter()
    use_case, repository, notifier = build(
        tmp_path, [FakeSource("fake", [offer])], criteria, profile, writer=writer
    )

    report = await use_case.run()

    assert writer.calls == 1
    assert report.notified == 1
    assert notifier.sent[0].score.value == 9
    assert "Backend Python remoto" in notifier.sent[0].summary
    repository.close()


async def test_una_fuente_caida_no_tumba_la_ejecucion(tmp_path, criteria, profile) -> None:
    class RotaSource:
        name = "rota"

        async def safe_search(self, _criteria):
            return []  # safe_search ya se traga la excepcion

    use_case, repository, notifier = build(
        tmp_path,
        [RotaSource(), FakeSource("buena", [make_offer()])],
        criteria,
        profile,
    )

    report = await use_case.run()

    assert report.per_source["rota"] == 0
    assert report.notified == 1
    repository.close()


async def test_lo_que_corta_el_tope_se_manda_en_la_siguiente_pasada(
    tmp_path, criteria, profile
) -> None:
    """Antes se perdian para siempre: quedaban guardadas como vistas, asi que
    la deteccion de duplicados impedia que volvieran a entrar nunca."""
    criteria.telegram.max_alerts_per_run = 1
    ofertas = [
        make_offer(external_id=str(i), url=f"https://example.com/{i}", company=f"Empresa{i}")
        for i in range(3)
    ]
    source = FakeSource("fake", ofertas)

    use_case, repository, notifier = build(tmp_path, [source], criteria, profile)
    primera = await use_case.run()

    assert primera.notified == 1
    assert primera.still_pending == 2

    # Segunda pasada: la fuente devuelve lo mismo, todo duplicado, y aun asi
    # sale una de la cola.
    segunda = await use_case.run()
    assert segunda.duplicates == 3
    assert segunda.notified == 1
    assert segunda.from_backlog == 1
    assert segunda.still_pending == 1

    # Y no se repite ninguna.
    urls = [item.offer.url for item in notifier.sent]
    assert len(urls) == len(set(urls))
    repository.close()


async def test_los_criterios_se_releen_en_cada_busqueda(tmp_path, criteria, profile, monkeypatch):
    """Tocar config.yaml obligaba a reiniciar el bot, y es justo el fichero
    que mas se toca."""
    import yaml

    from jobbot.container import Container

    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"scoring": {"notify_threshold": 6}}), encoding="utf-8")

    contenedor = Container.__new__(Container)
    contenedor.settings = type(
        "S", (), {"config_path": config, "salary_minimum": None, "salary_target": None}
    )()
    contenedor.criteria = __import__(
        "jobbot.domain.criteria", fromlist=["Criteria"]
    ).Criteria.load(config)
    assert contenedor.criteria.scoring.notify_threshold == 6

    config.write_text(yaml.safe_dump({"scoring": {"notify_threshold": 8}}), encoding="utf-8")
    assert contenedor.reload_criteria() is True
    assert contenedor.criteria.scoring.notify_threshold == 8

    # Sin cambios, no hace nada.
    assert contenedor.reload_criteria() is False

    # Y un fichero roto deja los criterios anteriores en pie.
    config.write_text("esto: no: es: yaml: valido:", encoding="utf-8")
    assert contenedor.reload_criteria() is False
    assert contenedor.criteria.scoring.notify_threshold == 8
