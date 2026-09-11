from __future__ import annotations

from jobbot.adapters.persistence import SqliteOfferRepository
from jobbot.adapters.telegram_notifier import format_offer
from jobbot.domain.fingerprint import fingerprint, url_key
from jobbot.domain.models import MatchScore, SalaryRange, ScoredOffer, WorkMode

from .conftest import make_offer


def scored(offer=None, value: int = 8, summary: str = "") -> ScoredOffer:
    offer = offer or make_offer()
    return ScoredOffer(
        offer=offer,
        score=MatchScore(value=value, reasons=("stack coincidente: python, aws",)),
        fingerprint=fingerprint(offer),
        summary=summary,
    )


def test_recuerda_y_reconoce(tmp_path) -> None:
    with SqliteOfferRepository(tmp_path / "db.sqlite3") as repository:
        item = scored()
        assert repository.is_known(item.fingerprint, url_key(item.offer.url)) is False

        repository.remember(item, notified=True, url_key=url_key(item.offer.url))

        assert repository.is_known(item.fingerprint, url_key(item.offer.url)) is True
        assert repository.stats()["enviadas"] == 1


def test_reconoce_por_url_aunque_cambie_el_titulo(tmp_path) -> None:
    with SqliteOfferRepository(tmp_path / "db.sqlite3") as repository:
        original = scored()
        repository.remember(original, notified=True, url_key=url_key(original.offer.url))

        renombrada = scored(make_offer(title="Backend Engineer Python - Nueva version"))
        assert repository.is_known(renombrada.fingerprint, url_key(renombrada.offer.url))


def test_top_pending_ordena_por_nota(tmp_path) -> None:
    with SqliteOfferRepository(tmp_path / "db.sqlite3") as repository:
        floja = scored(make_offer(external_id="1", url="https://e.com/1", company="Floja"), value=6)
        buena = scored(make_offer(external_id="2", url="https://e.com/2", company="Buena"), value=9)
        for item in (floja, buena):
            repository.remember(item, notified=False, url_key=url_key(item.offer.url))

        pendientes = repository.top_pending(limit=5)
        assert [item.offer.company for item in pendientes] == ["Buena", "Floja"]

        # Y con umbral, la floja no sale: /top no debe mandarte lo que la
        # busqueda automatica habria descartado por nota baja.
        buenas = repository.top_pending(limit=5, min_score=8)
        assert [item.offer.company for item in buenas] == ["Buena"]


def test_busqueda_por_prefijo_de_huella(tmp_path) -> None:
    with SqliteOfferRepository(tmp_path / "db.sqlite3") as repository:
        item = scored()
        repository.remember(item, notified=True, url_key=url_key(item.offer.url))

        encontrada = repository.find_by_fingerprint_prefix(item.fingerprint[:32])
        assert encontrada is not None
        assert encontrada.offer.title == item.offer.title


def test_mensaje_de_telegram_lleva_lo_importante() -> None:
    item = scored(summary="Backend Python remoto con Kubernetes, como AscendGate.")
    text = format_offer(item)

    assert "8/10" in text
    assert "Senior Backend Engineer (Python)" in text
    assert "Acme" in text
    assert "55.000€ - 65.000€" in text
    assert "https://example.com/jobs/1" in text
    assert "Backend Python remoto" in text


def test_mensaje_escapa_html_de_la_oferta() -> None:
    item = scored(make_offer(company="Acme <b>&</b> Co"))
    text = format_offer(item)
    assert "&lt;b&gt;" in text


def test_mensaje_sin_salario_lo_dice() -> None:
    item = scored(make_offer(salary=SalaryRange(), work_mode=WorkMode.UNKNOWN))
    text = format_offer(item)
    assert "no publicado" in text
    assert "Modalidad sin especificar" in text


async def test_el_notificador_espacia_los_mensajes() -> None:
    """Telegram descarta los envios seguidos en un mismo chat. Sin pausa,
    de 40 ofertas te llegarian 25 y las demas se perderian en silencio."""
    from jobbot.adapters.telegram_notifier import TelegramNotifier

    esperas: list[float] = []
    enviados: list[str] = []

    notifier = TelegramNotifier.__new__(TelegramNotifier)
    notifier._chat_id = "1"
    notifier._delay = 1.2
    notifier._sent_something = False

    class BotFalso:
        async def send_message(self, **kwargs):
            enviados.append(kwargs["text"])

    notifier._bot = BotFalso()

    async def dormir_falso(segundos: float) -> None:
        esperas.append(segundos)

    import jobbot.adapters.telegram_notifier as modulo

    original = modulo.asyncio.sleep
    modulo.asyncio.sleep = dormir_falso
    try:
        for _ in range(3):
            await notifier.send_text("hola")
    finally:
        modulo.asyncio.sleep = original

    assert len(enviados) == 3
    # El primero sale ya; los otros dos esperan su turno.
    assert esperas == [1.2, 1.2]
