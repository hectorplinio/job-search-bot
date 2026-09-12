"""Salida a Telegram: el mensaje que te llega al movil."""

from __future__ import annotations

import asyncio
import html
import logging
from datetime import date

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TelegramError

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
    if offer.applicants is not None:
        # Un "200+" al lado del titulo cambia la decision de aplicar o no.
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
    """Implementacion de Notifier sobre la Bot API.

    Telegram limita a un mensaje por segundo y pico en un mismo chat. Mandar
    treinta seguidos sin pausa hace que te descarte varios, y ademas llegan
    todos de golpe y no hay quien los lea. De ahi el ritmo entre envios.
    """

    def __init__(self, token: str, chat_id: str, *, delay_seconds: float = 1.2) -> None:
        self._bot = Bot(token=token)
        self._chat_id = chat_id
        self._delay = delay_seconds
        self._sent_something = False

    async def _pace(self) -> None:
        """Espera antes de cada mensaje menos el primero."""
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
                # Telegram dice exactamente cuanto esperar. Hacerle caso es
                # la diferencia entre recibir 40 ofertas o recibir 25.
                espera = float(getattr(exc, "retry_after", 5)) + 0.5
                logger.warning("Telegram pide esperar %.1fs; reintento %s", espera, intento + 1)
                await asyncio.sleep(espera)
            except TelegramError:
                logger.exception("No se pudo enviar %s", what)
                return False
            else:
                return True

        logger.error("Telegram sigue limitando; %s no se envio", what)
        return False

    async def send_offer(self, scored: ScoredOffer) -> None:
        await self._send(
            format_offer(scored),
            reply_markup=_keyboard(scored),
            what=f"la oferta {scored.offer.url}",
        )

    async def send_text(self, text: str) -> None:
        await self._send(text, what="el mensaje de texto")
