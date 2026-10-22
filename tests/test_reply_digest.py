"""The grouped Telegram digest: one message for a whole check-mail run
instead of one per reply."""

from __future__ import annotations

from datetime import UTC, datetime

from jobbot.adapters.telegram_notifier import format_replies_digest
from jobbot.domain.reply_models import ClassifiedReply, EmailReply, ReplyCategory


def make_classified(category: ReplyCategory, **overrides) -> ClassifiedReply:
    reply = EmailReply(
        message_id=overrides.pop("message_id", "m1"),
        thread_id="t1",
        sender="Acme Recruiting <jobs@acme.example>",
        subject=overrides.pop("subject", "Tu candidatura"),
        snippet="",
        body="",
        received_at=datetime(2026, 10, 13, tzinfo=UTC),
    )
    return ClassifiedReply(
        reply=reply,
        category=category,
        company_guess=overrides.pop("company_guess", "Acme"),
    )


def test_sin_correos_dice_que_no_hay_nada():
    text = format_replies_digest([])
    assert "Sin correos nuevos" in text


def test_agrupa_por_categoria_con_entrevista_primero():
    items = [
        make_classified(ReplyCategory.REJECTED, message_id="m1", company_guess="Foo"),
        make_classified(ReplyCategory.INTERVIEW, message_id="m2", company_guess="Bar"),
    ]
    text = format_replies_digest(items)

    assert text.index("Entrevista") < text.index("Rechazo")
    assert "Foo" in text
    assert "Bar" in text


def test_cuenta_el_total_en_la_cabecera():
    items = [
        make_classified(ReplyCategory.INTERVIEW, message_id="m1"),
        make_classified(ReplyCategory.REJECTED, message_id="m2"),
        make_classified(ReplyCategory.REJECTED, message_id="m3"),
    ]
    text = format_replies_digest(items)

    assert "3 correos nuevos" in text
    assert "Rechazo</b> (2)" in text
    assert "Entrevista</b> (1)" in text


def test_escapa_html_de_la_empresa_y_el_asunto():
    item = make_classified(
        ReplyCategory.INTERVIEW,
        company_guess="Acme & Co",
        subject="<script>alert(1)</script>",
    )
    text = format_replies_digest([item])

    assert "<script>" not in text
    assert "Acme &amp; Co" in text


def test_una_sola_linea_por_correo():
    items = [
        make_classified(ReplyCategory.INTERVIEW, message_id="m1", subject="Entrevista A"),
        make_classified(ReplyCategory.INTERVIEW, message_id="m2", subject="Entrevista B"),
    ]
    text = format_replies_digest(items)

    assert "Entrevista A" in text
    assert "Entrevista B" in text
    assert text.count("•") == 2
