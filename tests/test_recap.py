"""build_recap(): one row per conversation thread, not per email."""

from __future__ import annotations

from datetime import UTC, datetime

from jobbot.domain.recap import build_recap
from jobbot.domain.reply_models import ClassifiedReply, EmailReply, ReplyCategory


def make_classified(
    *, thread_id: str, sender: str, category: ReplyCategory, company_guess: str, **overrides
) -> ClassifiedReply:
    reply = EmailReply(
        message_id=overrides.pop("message_id", f"{thread_id}-m"),
        thread_id=thread_id,
        sender=sender,
        subject=overrides.pop("subject", "Tu candidatura"),
        snippet="",
        body="",
        received_at=overrides.pop("received_at", datetime(2026, 10, 1, tzinfo=UTC)),
    )
    return ClassifiedReply(reply=reply, category=category, company_guess=company_guess)


def test_una_fila_por_hilo_no_por_correo():
    items = [
        make_classified(
            thread_id="t1",
            sender="Acme Recruiting <jobs@acme.example>",
            category=ReplyCategory.AUTO_CONFIRMATION,
            company_guess="Acme",
            message_id="m1",
            received_at=datetime(2026, 10, 1, tzinfo=UTC),
        ),
        make_classified(
            thread_id="t1",
            sender="Hector <hector@example.com>",
            category=ReplyCategory.INTERVIEW,
            company_guess="Hector",
            message_id="m2",
            received_at=datetime(2026, 10, 5, tzinfo=UTC),
        ),
    ]
    recap = build_recap(items)

    assert len(recap) == 1


def test_la_empresa_viene_del_primer_mensaje_del_hilo():
    """El ultimo mensaje de un hilo suele ser tuyo (un seguimiento), y ahi
    guess_company() devuelve tu propio nombre, no la empresa. El primero casi
    siempre es de verdad del reclutador."""
    items = [
        make_classified(
            thread_id="t1",
            sender="Marta Recruiter <marta@initech.example>",
            category=ReplyCategory.INFO_REQUEST,
            company_guess="Initech",
            message_id="m1",
            received_at=datetime(2026, 10, 1, tzinfo=UTC),
        ),
        make_classified(
            thread_id="t1",
            sender="Hector Plinio Navarro <hector@example.com>",
            category=ReplyCategory.INTERVIEW,
            company_guess="Hector Plinio Navarro",
            message_id="m2",
            received_at=datetime(2026, 10, 5, tzinfo=UTC),
        ),
    ]
    recap = build_recap(items)

    assert recap[0].company == "Initech"


def test_el_estado_viene_del_mensaje_mas_reciente():
    items = [
        make_classified(
            thread_id="t1",
            sender="Acme <jobs@acme.example>",
            category=ReplyCategory.INTERVIEW,
            company_guess="Acme",
            message_id="m1",
            received_at=datetime(2026, 10, 1, tzinfo=UTC),
        ),
        make_classified(
            thread_id="t1",
            sender="Acme <jobs@acme.example>",
            category=ReplyCategory.REJECTED,
            company_guess="Acme",
            message_id="m2",
            received_at=datetime(2026, 10, 10, tzinfo=UTC),
        ),
    ]
    recap = build_recap(items)

    assert recap[0].category == ReplyCategory.REJECTED


def test_ordenado_por_actividad_mas_reciente_primero():
    items = [
        make_classified(
            thread_id="old",
            sender="Foo <jobs@foo.example>",
            category=ReplyCategory.REJECTED,
            company_guess="Foo",
            message_id="m1",
            received_at=datetime(2026, 9, 1, tzinfo=UTC),
        ),
        make_classified(
            thread_id="new",
            sender="Bar <jobs@bar.example>",
            category=ReplyCategory.INTERVIEW,
            company_guess="Bar",
            message_id="m2",
            received_at=datetime(2026, 10, 10, tzinfo=UTC),
        ),
    ]
    recap = build_recap(items)

    assert [s.company for s in recap] == ["Bar", "Foo"]


def test_hilo_de_puro_ruido_se_descarta():
    items = [
        make_classified(
            thread_id="t1",
            sender="Alerts <alerts@board.example>",
            category=ReplyCategory.NOISE,
            company_guess="Board",
            message_id="m1",
        )
    ]
    recap = build_recap(items)

    assert recap == []


def test_el_contacto_es_el_remitente_del_ultimo_mensaje():
    items = [
        make_classified(
            thread_id="t1",
            sender="Jane Recruiter <jane@acme.example>",
            category=ReplyCategory.INTERVIEW,
            company_guess="Acme",
            message_id="m1",
        )
    ]
    recap = build_recap(items)

    assert recap[0].contact == "Jane Recruiter"
