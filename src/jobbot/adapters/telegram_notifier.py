"""The way out to Telegram: the message that reaches your phone."""

from __future__ import annotations

import asyncio
import html
import logging
from datetime import date

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TelegramError

from ..domain.models import ScoredOffer, WorkMode
from ..domain.public_models import ScoredOposicion
from ..domain.recap import ThreadStatus
from ..domain.reply_models import ClassifiedReply, ReplyCategory

logger = logging.getLogger(__name__)

SCORE_ICONS = {10: "🟢", 9: "🟢", 8: "🟢", 7: "🟡", 6: "🟡"}
GRUPO_LABELS = {
    "a1": "A1",
    "a2": "A2",
    "c1": "C1",
    "c2": "C2",
    "desconocido": "grupo sin especificar",
}
TURNO_LABELS = {
    "libre": "turno libre",
    "promocion_interna": "promoción interna",
    "desconocido": "turno sin especificar",
}
MODE_LABELS = {
    WorkMode.REMOTE: "Remoto",
    WorkMode.HYBRID: "Híbrido",
    WorkMode.ONSITE: "Presencial",
    WorkMode.UNKNOWN: "Modalidad sin especificar",
}
REPLY_ICONS = {
    ReplyCategory.OFFER: "🎉",
    ReplyCategory.INTERVIEW: "📅",
    ReplyCategory.REJECTED: "❌",
    ReplyCategory.INFO_REQUEST: "❓",
    ReplyCategory.AUTO_CONFIRMATION: "📨",
    ReplyCategory.NOISE: "🔕",
    ReplyCategory.UNKNOWN: "📬",
}
REPLY_LABELS = {
    ReplyCategory.OFFER: "Oferta",
    ReplyCategory.INTERVIEW: "Entrevista",
    ReplyCategory.REJECTED: "Rechazo",
    ReplyCategory.INFO_REQUEST: "Piden información",
    ReplyCategory.AUTO_CONFIRMATION: "Confirmación automática",
    ReplyCategory.NOISE: "Ruido",
    ReplyCategory.UNKNOWN: "Sin clasificar",
}


def _escape(value: str) -> str:
    return html.escape(value or "", quote=False)


def _age(posted_at: date | None) -> str:
    if posted_at is None:
        return ""
    days = (date.today() - posted_at).days
    if days <= 0:
        return "hoy"
    if days == 1:
        return "ayer"
    return f"hace {days} días"


def format_offer(scored: ScoredOffer) -> str:
    """The body of the message. Isolated so it can be tested without a network."""
    offer = scored.offer
    icon = SCORE_ICONS.get(scored.score.value, "⚪")

    lines = [
        f"{icon} <b>{scored.score.value}/10</b> · <b>{_escape(offer.title)}</b>",
        f"🏢 {_escape(offer.company)}",
    ]

    place = [MODE_LABELS[offer.work_mode]]
    if offer.location:
        place.append(_escape(offer.location))
    lines.append(f"📍 {' · '.join(place)}")
    lines.append(f"💰 {_escape(offer.salary.format())}")
    if offer.applicants is not None:
        # A "200+" next to the title changes whether you apply at all.
        cuantos = f"{offer.applicants}+" if offer.applicants >= 200 else str(offer.applicants)
        lines.append(f"👥 {cuantos} solicitudes")

    summary = scored.summary or "; ".join(scored.score.reasons)
    if summary:
        lines.append("")
        lines.append(f"<i>{_escape(summary)}</i>")

    footer = [offer.source]
    if age := _age(offer.posted_at):
        footer.append(age)
    lines.append("")
    lines.append(f'<a href="{_escape(offer.url)}">Ver oferta</a> · {" · ".join(footer)}')
    return "\n".join(lines)


def format_oposicion(scored: ScoredOposicion) -> str:
    """The body of a public-sector alert. Isolated so it can be tested
    without a network, same as format_offer()."""
    op = scored.oposicion
    icon = "🚨" if scored.score.urgent else "🏛️"

    lines = [f"{icon} <b>{_escape(op.titulo)}</b>", f"🏢 {_escape(op.organismo)}"]

    detalle = [GRUPO_LABELS.get(op.grupo.value, op.grupo.value)]
    detalle.append(TURNO_LABELS.get(op.turno.value, op.turno.value))
    lines.append(f"🎓 {' · '.join(detalle)}")

    if not op.elegible:
        lines.append("⚠️ <b>NO ELEGIBLE: requiere grado universitario</b>")

    if op.fecha_limite_aproximada:
        dias_restantes = (op.fecha_limite_aproximada - date.today()).days
        if dias_restantes >= 0:
            lines.append(
                f"⏳ Plazo aproximado hasta {op.fecha_limite_aproximada.isoformat()} "
                f"({dias_restantes} días)"
            )
        else:
            lines.append("⏳ Plazo probablemente cerrado")

    summary = scored.summary or "; ".join(scored.score.reasons)
    if summary:
        lines.append("")
        lines.append(f"<i>{_escape(summary)}</i>")

    lines.append("")
    lines.append(f'<a href="{_escape(op.url)}">Ver en el {op.fuente.upper()}</a>')
    return "\n".join(lines)


def format_reply(classified: ClassifiedReply) -> str:
    """The body of a single reply alert. Kept for `/correo <id>`-style
    lookups later; the scheduled check uses format_replies_digest() instead
    so a run reads as one message, not one per reply."""
    reply = classified.reply
    icon = REPLY_ICONS[classified.category]
    label = REPLY_LABELS[classified.category]

    lines = [f"{icon} <b>{label}</b>"]
    if classified.company_guess:
        lines.append(f"🏢 {_escape(classified.company_guess)}")
    lines.append(f"✉️ {_escape(reply.subject)}")

    snippet = reply.snippet or reply.body[:200]
    if snippet:
        lines.append("")
        lines.append(f"<i>{_escape(snippet)}</i>")

    return "\n".join(lines)


# Category order within the digest: most actionable first. NOISE and
# AUTO_CONFIRMATION never reach here - CheckReplies filters them out before
# notifying, see needs_action.
_DIGEST_ORDER = (
    ReplyCategory.OFFER,
    ReplyCategory.INTERVIEW,
    ReplyCategory.REJECTED,
    ReplyCategory.INFO_REQUEST,
    ReplyCategory.UNKNOWN,
)


_RECAP_ORDER = (
    ReplyCategory.OFFER,
    ReplyCategory.INTERVIEW,
    ReplyCategory.INFO_REQUEST,
    ReplyCategory.UNKNOWN,
    ReplyCategory.AUTO_CONFIRMATION,
    ReplyCategory.REJECTED,
)


def format_recap(statuses: list[ThreadStatus]) -> str:
    """The status of every conversation that is still worth a glance, one
    line each, grouped by where it stands - not a wall of individual
    emails, and not just the new ones either: the whole picture at once."""
    if not statuses:
        return "📭 No hay ningun hilo de correo registrado todavia."

    by_category: dict[ReplyCategory, list[ThreadStatus]] = {}
    for status in statuses:
        by_category.setdefault(status.category, []).append(status)

    lines = [f"🗂️ <b>Resumen de {len(statuses)} procesos</b>"]
    for category in _RECAP_ORDER:
        items = by_category.get(category)
        if not items:
            continue
        lines.append("")
        lines.append(f"{REPLY_ICONS[category]} <b>{REPLY_LABELS[category]}</b> ({len(items)})")
        for status in items:
            company = _escape(status.company)
            contact = _escape(status.contact)
            age = _age(status.last_update.date())
            lines.append(f"• <b>{company}</b> ({contact}) — {age}")

    return "\n".join(lines)


def format_replies_digest(classified: list[ClassifiedReply]) -> str:
    """One message for the whole run instead of one per reply, grouped by
    category - a run of sixty replies used to mean sixty notifications; this
    is the one-screen version of the same information."""
    if not classified:
        return "📬 Sin correos nuevos que merezca la pena avisar."

    by_category: dict[ReplyCategory, list[ClassifiedReply]] = {}
    for item in classified:
        by_category.setdefault(item.category, []).append(item)

    lines = [f"📬 <b>{len(classified)} correos nuevos</b>"]
    for category in _DIGEST_ORDER:
        items = by_category.get(category)
        if not items:
            continue
        lines.append("")
        lines.append(f"{REPLY_ICONS[category]} <b>{REPLY_LABELS[category]}</b> ({len(items)})")
        for item in items:
            company = _escape(item.company_guess or "?")
            subject = _escape(item.reply.subject or "(sin asunto)")
            lines.append(f"• <b>{company}</b> — {subject}")

    return "\n".join(lines)


def _keyboard(scored: ScoredOffer) -> InlineKeyboardMarkup:
    # callback_data is capped at 64 bytes, so the fingerprint goes truncated.
    key = scored.fingerprint[:32]
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✍️ Cover letter", callback_data=f"cover:{key}"),
                InlineKeyboardButton("📄 Summary", callback_data=f"summary:{key}"),
            ]
        ]
    )


class TelegramNotifier:
    """Notifier implemented on the Bot API.

    Telegram allows roughly one message per second in the same chat. Sending
    thirty back to back means several get dropped, and they all land at once
    so nobody can read them. Hence the pacing between sends.
    """

    def __init__(self, token: str, chat_id: str, *, delay_seconds: float = 1.2) -> None:
        self._bot = Bot(token=token)
        self._chat_id = chat_id
        self._delay = delay_seconds
        self._sent_something = False

    async def _pace(self) -> None:
        """Waits before every message except the first."""
        if self._sent_something and self._delay > 0:
            await asyncio.sleep(self._delay)
        self._sent_something = True

    async def _send(self, text: str, reply_markup=None, *, what: str) -> bool:
        await self._pace()
        for intento in range(3):
            try:
                await self._bot.send_message(
                    chat_id=self._chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                    reply_markup=reply_markup,
                )
            except RetryAfter as exc:
                # Telegram says exactly how long to wait. Obeying it is the
                # difference between receiving 40 postings and receiving 25.
                espera = float(getattr(exc, "retry_after", 5)) + 0.5
                logger.warning("Telegram asks to wait %.1fs; retry %s", espera, intento + 1)
                await asyncio.sleep(espera)
            except TelegramError:
                logger.exception("Could not send %s", what)
                return False
            else:
                return True

        logger.error("Telegram is still rate limiting; %s was not sent", what)
        return False

    async def send_offer(self, scored: ScoredOffer) -> None:
        await self._send(
            format_offer(scored),
            reply_markup=_keyboard(scored),
            what=f"la oferta {scored.offer.url}",
        )

    async def send_text(self, text: str) -> None:
        await self._send(text, what="el mensaje de texto")

    async def send_oposicion(self, scored: ScoredOposicion) -> None:
        await self._send(
            format_oposicion(scored),
            what=f"la oposicion {scored.oposicion.identificador}",
        )

    async def send_reply(self, classified: ClassifiedReply) -> None:
        await self._send(
            format_reply(classified),
            what=f"la respuesta {classified.reply.message_id}",
        )

    async def send_replies_digest(self, classified: list[ClassifiedReply]) -> None:
        # Same 4096-char Telegram ceiling _reply_long() works around in
        # bot.py; a run with dozens of replies still has to go out somehow.
        text = format_replies_digest(classified)
        for start in range(0, len(text), 3900):
            await self._send(text[start : start + 3900], what="el resumen de correo")
