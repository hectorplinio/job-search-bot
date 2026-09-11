"""Salida a Telegram: el mensaje que te llega al movil."""

from __future__ import annotations

import html
import logging
from datetime import date

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError

from ..domain.models import ScoredOffer, WorkMode

logger = logging.getLogger(__name__)

SCORE_ICONS = {10: "🟢", 9: "🟢", 8: "🟢", 7: "🟡", 6: "🟡"}
MODE_LABELS = {
    WorkMode.REMOTE: "Remoto",
    WorkMode.HYBRID: "Híbrido",
    WorkMode.ONSITE: "Presencial",
    WorkMode.UNKNOWN: "Modalidad sin especificar",
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
    """El cuerpo del mensaje. Aislado para poder testearlo sin red."""
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


def _keyboard(scored: ScoredOffer) -> InlineKeyboardMarkup:
    # callback_data tiene un limite de 64 bytes, asi que va la huella recortada.
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
    """Implementacion de Notifier sobre la Bot API."""

    def __init__(self, token: str, chat_id: str) -> None:
        self._bot = Bot(token=token)
        self._chat_id = chat_id

    async def send_offer(self, scored: ScoredOffer) -> None:
        try:
            await self._bot.send_message(
                chat_id=self._chat_id,
                text=format_offer(scored),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=_keyboard(scored),
            )
        except TelegramError:
            logger.exception("No se pudo enviar la oferta %s", scored.offer.url)

    async def send_text(self, text: str) -> None:
        try:
            await self._bot.send_message(
                chat_id=self._chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except TelegramError:
            logger.exception("No se pudo enviar el mensaje de texto")
