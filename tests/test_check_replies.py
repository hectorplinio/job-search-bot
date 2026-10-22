"""The reply-tracking use case: fakes for source/repository/notifier, no
network and no real mailbox."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from jobbot.application.check_replies import CheckReplies
from jobbot.domain.reply_classification import classify
from jobbot.domain.reply_models import ClassifiedReply, EmailReply, ReplyCategory


def make_reply(message_id: str, body: str, **overrides) -> EmailReply:
    defaults = dict(
        message_id=message_id,
        thread_id=f"thread-{message_id}",
        sender="Acme Recruiting <jobs@acme.example>",
        subject="Tu candidatura",
        snippet=body[:50],
        body=body,
        received_at=datetime(2026, 10, 13, tzinfo=UTC),
    )
    defaults.update(overrides)
    return EmailReply(**defaults)


class FakeSource:
    def __init__(self, replies: list[EmailReply]) -> None:
        self.replies = replies
        self.last_query: str | None = None

    async def search(self, query: str, *, max_results: int = 50):
        self.last_query = query
        return self.replies


class FakeRepository:
    def __init__(self, known_ids: set[str] | None = None) -> None:
        self.known_ids = known_ids or set()
        self.remembered: list[ClassifiedReply] = []
        self.notified_ids: list[str] = []

    def is_known(self, message_id: str) -> bool:
        return message_id in self.known_ids

    def remember(self, classified: ClassifiedReply, *, notified: bool) -> None:
        self.remembered.append(classified)

    def mark_notified(self, message_id: str) -> None:
        self.notified_ids.append(message_id)

    def pending(self, limit: int):
        return []


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[ClassifiedReply] = []
        self.digest_calls: int = 0

    async def send_replies_digest(self, classified: list[ClassifiedReply]) -> None:
        self.digest_calls += 1
        self.sent.extend(classified)


@pytest.fixture
def replies() -> list[EmailReply]:
    return [
        make_reply("m1", "Nos gustaria agendar una entrevista contigo."),
        make_reply("m2", "Hemos recibido tu candidatura. Gracias por tu interes."),
        make_reply("m3", "Hemos decidido no continuar con tu candidatura."),
    ]


@pytest.mark.asyncio
async def test_notifica_solo_lo_que_merece_la_pena(replies):
    source = FakeSource(replies)
    repository = FakeRepository()
    notifier = FakeNotifier()
    use_case = CheckReplies(source=source, repository=repository, notifier=notifier, days_back=3)

    report = await use_case.run()

    # m2 es confirmacion automatica: se guarda en la base, pero no avisa.
    assert {c.reply.message_id for c in notifier.sent} == {"m1", "m3"}
    assert report.notified == 2
    assert len(repository.remembered) == 3
    # Un solo aviso agrupado, no uno por correo.
    assert notifier.digest_calls == 1


@pytest.mark.asyncio
async def test_no_repite_un_mensaje_ya_conocido(replies):
    source = FakeSource(replies)
    repository = FakeRepository(known_ids={"m1"})
    notifier = FakeNotifier()
    use_case = CheckReplies(source=source, repository=repository, notifier=notifier, days_back=3)

    report = await use_case.run()

    assert report.duplicates == 1
    assert {c.reply.message_id for c in notifier.sent} == {"m3"}


@pytest.mark.asyncio
async def test_dry_run_no_toca_el_repositorio_ni_el_notificador(replies):
    source = FakeSource(replies)
    repository = FakeRepository()
    notifier = FakeNotifier()
    use_case = CheckReplies(source=source, repository=repository, notifier=notifier, days_back=3)

    await use_case.run(dry_run=True)

    assert repository.remembered == []
    assert notifier.sent == []


@pytest.mark.asyncio
async def test_usa_una_busqueda_acotada_al_rango_de_dias(replies):
    source = FakeSource(replies)
    use_case = CheckReplies(
        source=source, repository=FakeRepository(), notifier=FakeNotifier(), days_back=60
    )

    await use_case.run()

    assert source.last_query is not None
    assert source.last_query.startswith("newer_than:60d (")


def test_sanity_check_de_las_fixtures_contra_el_clasificador_real(replies):
    """Si esto falla, el resto de este archivo esta probando contra
    fixtures que ya no representan lo que classify() hace de verdad."""
    categories = {r.message_id: classify(r).category for r in replies}
    assert categories == {
        "m1": ReplyCategory.INTERVIEW,
        "m2": ReplyCategory.AUTO_CONFIRMATION,
        "m3": ReplyCategory.REJECTED,
    }
