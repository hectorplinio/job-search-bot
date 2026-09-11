"""El bot de Telegram: comandos, botones y modo manual.

Ejecuta `jobbot bot` y le puedes hablar. El cron (`jobbot run`) funciona sin
esto; el bot es para pedirle cosas tu.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .adapters.offer_reader import UnreadableOffer
from .adapters.telegram_notifier import format_offer
from .application.write_documents import extract_url
from .container import Container
from .domain.models import ApplicationDocuments, JobOffer
from .settings import Settings

logger = logging.getLogger(__name__)

TELEGRAM_LIMIT = 3900

HELP = """\
<b>Buscador de ofertas</b>

/buscar - lanza una busqueda ahora mismo
/top - las mejores ofertas pendientes de mandarte
/oferta &lt;url&gt; - cover letter + summary para esa oferta
/carta &lt;url&gt; - solo la cover letter
/summary &lt;url&gt; - solo el summary del CV
/stats - que lleva visto el bot
/ayuda - esto

Tambien puedes pegarme el enlace de una oferta sin mas, o el texto de la
oferta si el portal pide login.
"""


def _container(context: ContextTypes.DEFAULT_TYPE) -> Container:
    return context.application.bot_data["container"]


async def _reply_long(update: Update, text: str) -> None:
    """Telegram corta a 4096 caracteres."""
    message = update.effective_message
    if message is None:
        return
    for start in range(0, len(text), TELEGRAM_LIMIT):
        await message.reply_text(
            text[start : start + TELEGRAM_LIMIT],
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


def _format_documents(offer: JobOffer, documents: ApplicationDocuments) -> tuple[str, str]:
    header = f"<b>{offer.title}</b>" + (f" · {offer.company}" if offer.company else "")
    stack = ", ".join(documents.detected_stack) or "no detectado"
    cover = (
        f"{header}\n<i>Stack de la oferta: {stack}</i>\n\n"
        f"<b>COVER LETTER</b>\n\n{documents.cover_letter}"
    )
    summary = f"<b>CV SUMMARY ADAPTADO</b>\n\n{documents.cv_summary}"
    if documents.highlighted_experience:
        summary += "\n\n<i>Destaca: " + "; ".join(documents.highlighted_experience) + "</i>"
    return cover, summary


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply_long(update, HELP)


async def search_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    await message.reply_text("🔎 Buscando. Esto tarda un par de minutos.")
    await message.chat.send_action(ChatAction.TYPING)

    container = _container(context)
    report = await container.search_use_case().run()
    await _reply_long(update, report.as_text())


async def top_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    container = _container(context)
    pending = container.repository.top_pending(limit=5)
    if not pending:
        await update.effective_message.reply_text("No hay ofertas pendientes.")
        return
    for item in pending:
        await _reply_long(update, format_offer(item))
        container.repository.mark_notified(item.fingerprint)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    numbers = _container(context).repository.stats()
    lines = [f"{key}: <b>{value}</b>" for key, value in numbers.items()]
    await _reply_long(update, "📊 <b>Historial</b>\n" + "\n".join(lines))


async def _documents_for(update: Update, context: ContextTypes.DEFAULT_TYPE, raw: str,
                         *, want_cover: bool, want_summary: bool) -> None:
    message = update.effective_message
    if not raw.strip():
        await message.reply_text("Pasame el enlace de la oferta o pega su texto.")
        return

    await message.chat.send_action(ChatAction.TYPING)
    container = _container(context)
    try:
        offer, documents = await container.write_use_case().from_input(raw)
    except UnreadableOffer as exc:
        await message.reply_text(
            f"{exc}\n\nSi el portal pide login, copia el texto de la oferta y pegamelo."
        )
        return
    except Exception:  # noqa: BLE001 - el bot no puede morirse por una oferta rara
        logger.exception("Fallo generando documentos")
        await message.reply_text("Algo ha fallado generando los documentos. Mira los logs.")
        return

    cover, summary = _format_documents(offer, documents)
    if want_cover:
        await _reply_long(update, cover)
    if want_summary:
        await _reply_long(update, summary)


async def offer_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw = " ".join(context.args or [])
    await _documents_for(update, context, raw, want_cover=True, want_summary=True)


async def cover_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw = " ".join(context.args or [])
    await _documents_for(update, context, raw, want_cover=True, want_summary=False)


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw = " ".join(context.args or [])
    await _documents_for(update, context, raw, want_cover=False, want_summary=True)


async def free_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Un enlace suelto, o el texto de una oferta, dispara el modo manual."""
    text = update.effective_message.text or ""
    if extract_url(text) is None and len(text) < 200:
        await update.effective_message.reply_text(
            "Mandame el enlace de una oferta, o pega su texto. /ayuda para lo demas."
        )
        return
    await _documents_for(update, context, text, want_cover=True, want_summary=True)


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Botones 'Cover letter' y 'Summary' de las alertas."""
    query = update.callback_query
    await query.answer()

    action, _, prefix = (query.data or "").partition(":")
    container = _container(context)
    stored = container.repository.find_by_fingerprint_prefix(prefix)
    if stored is None:
        await query.message.reply_text("Esa oferta ya no esta en el historial.")
        return

    await query.message.chat.send_action(ChatAction.TYPING)
    try:
        documents = await container.write_use_case().from_offer(stored.offer)
    except Exception:  # noqa: BLE001
        logger.exception("Fallo generando documentos desde un boton")
        await query.message.reply_text("No he podido generar los documentos.")
        return

    cover, summary = _format_documents(stored.offer, documents)
    body = cover if action == "cover" else summary
    for start in range(0, len(body), TELEGRAM_LIMIT):
        await query.message.reply_text(
            body[start : start + TELEGRAM_LIMIT],
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


def build_application(settings: Settings | None = None) -> Application:
    settings = settings or Settings.from_env()
    token, chat_id = settings.require_telegram()
    container = Container(settings)

    async def post_init(application: Application) -> None:
        await container.__aenter__()
        application.bot_data["container"] = container
        logger.info("Bot listo. Escuchando solo al chat %s", chat_id)

    async def post_shutdown(_application: Application) -> None:
        await container.__aexit__(None, None, None)

    application = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Solo tu chat. Sin esto, cualquiera que encuentre el bot gasta tu cuota
    # de Anthropic generando cartas.
    only_me = filters.Chat(chat_id=int(chat_id))

    application.add_handler(CommandHandler(["start", "ayuda", "help"], start, filters=only_me))
    application.add_handler(CommandHandler("buscar", search_now, filters=only_me))
    application.add_handler(CommandHandler("top", top_pending, filters=only_me))
    application.add_handler(CommandHandler("stats", stats, filters=only_me))
    application.add_handler(CommandHandler("oferta", offer_command, filters=only_me))
    application.add_handler(CommandHandler("carta", cover_command, filters=only_me))
    application.add_handler(CommandHandler("summary", summary_command, filters=only_me))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & only_me, free_text)
    )
    return application


def run_bot() -> None:
    build_application().run_polling(allowed_updates=Update.ALL_TYPES)
