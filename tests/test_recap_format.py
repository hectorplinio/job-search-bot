"""format_recap(): the Telegram rendering of build_recap()'s output."""

from __future__ import annotations

from datetime import UTC, datetime

from jobbot.adapters.telegram_notifier import format_recap
from jobbot.domain.recap import ThreadStatus
from jobbot.domain.reply_models import ReplyCategory


def make_status(**overrides) -> ThreadStatus:
    defaults = dict(
        company="Acme",
        contact="Jane Recruiter",
        category=ReplyCategory.INTERVIEW,
        subject="Tu candidatura",
        last_update=datetime.now(UTC),
    )
    defaults.update(overrides)
    return ThreadStatus(**defaults)


def test_sin_procesos_lo_dice():
    text = format_recap([])
    assert "No hay ningun hilo" in text


def test_cuenta_el_total_y_agrupa_por_categoria():
    statuses = [
        make_status(company="Acme", category=ReplyCategory.INTERVIEW),
        make_status(company="Foo", category=ReplyCategory.REJECTED),
        make_status(company="Bar", category=ReplyCategory.REJECTED),
    ]
    text = format_recap(statuses)

    assert "Resumen de 3 procesos" in text
    assert "Rechazo</b> (2)" in text
    assert "Entrevista</b> (1)" in text


def test_escapa_html_de_empresa_y_contacto():
    status = make_status(company="Acme & Co", contact="Jane <jane@acme.example>")
    text = format_recap([status])

    assert "Acme &amp; Co" in text
    assert "Jane &lt;jane@acme.example&gt;" in text
