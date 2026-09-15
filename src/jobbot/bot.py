"""The Telegram bot: commands, buttons and manual mode.

Run `jobbot bot` and you can talk to it. The cron job (`jobbot run`) works
without this; the bot is for asking it things yourself.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from telegram import Message, Update
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
from .application.write_documents import extract_url
from .container import Container
from .domain.cost import format_cost
from .domain.models import ApplicationDocuments, JobOffer
from .settings import Settings

logger = logging.getLogger(__name__)

TELEGRAM_LIMIT = 3900
SEARCH_JOB = "busqueda-periodica"

HELP = """\
<b>Buscador de ofertas</b>

/buscar - lanza una busqueda ahora mismo
/top - las mejores ofertas pendientes de mandarte
/oferta &lt;url&gt; - cover letter + summary para esa oferta
/carta &lt;url&gt; - solo la cover letter
/summary &lt;url&gt; - solo el summary del CV
/stats - que lleva visto el bot
/usage - cuanto llevas gastado en la API de Claude
/proxima - cuando toca la siguiente busqueda automatica
/ayuda - esto

Tambien puedes pegarme el enlace de una oferta sin mas, o el texto de la
oferta si el portal pide login.
"""


def _container(context: ContextTypes.DEFAULT_TYPE) -> Container:
    return context.application.bot_data["container"]


async def _reply_long(update: Update, text: str) -> None:
    """Telegram cuts messages off at 4096 characters."""
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


async def scheduled_search(context: ContextTypes.DEFAULT_TYPE) -> None:
    """The scheduled search, inside the bot's own process.

    It says nothing when it finds nothing: at four runs a day, a "nothing
    new" every time would be noise. The postings speak for themselves.
    """
    container = context.application.bot_data["container"]
    try:
        report = await container.search_use_case().run()
    except Exception:  # noqa: BLE001 - one failure must not kill the bot
        logger.exception("La busqueda programada fallo; se reintenta en el proximo turno")
        return
    logger.info("Busqueda programada: %s enviadas de %s revisadas", report.notified, report.fetched)


async def next_run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """When the next automatic search is due."""
    queue = context.application.job_queue
    trabajos = queue.get_jobs_by_name(SEARCH_JOB) if queue is not None else []

    cuando = None
    if trabajos:
        # next_t only exists while the scheduler is running; outside it, it
        # raises AttributeError instead of returning None.
        try:
            cuando = trabajos[0].next_t
        except AttributeError:
            cuando = None

    message = update.effective_message
    if message is None:
        return

    if cuando is None:
        await message.reply_text(
            "No hay busqueda automatica programada ahora mismo. Usa /buscar cuando quieras."
        )
        return

    local = cuando.astimezone()
    await message.reply_text(f"Siguiente busqueda automatica: {local:%H:%M} del {local:%d/%m}.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply_long(update, HELP)


async def search_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    await message.reply_text("🔎 Buscando. Esto tarda un par de minutos.")
    await message.chat.send_action(ChatAction.TYPING)

    container = _container(context)
    report = await container.search_use_case().run()
    await _reply_long(update, report.as_text())


async def top_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The best pending postings, exactly like an alert.

    They go through the notifier rather than reply_text: that is the only
    place that wires up the Cover letter and Summary buttons. Sending them any
    other way left them without those.
    """
    container = _container(context)
    umbral = container.criteria.scoring.notify_threshold
    pending = container.repository.top_pending(limit=5, min_score=umbral)
    if not pending:
        await _reply_long(update, f"No hay ofertas pendientes con nota {umbral} o mas.")
        return

    notifier = container.notifier()
    for item in pending:
        await notifier.send_offer(item)
        container.repository.mark_notified(item.fingerprint)


async def usage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """What you have spent on Claude so far, counted by the bot itself."""
    log = _container(context).usage
    resumen = log.summary()

    lineas = ["💳 <b>Gasto en la API de Claude</b>", ""]
    for periodo, datos in resumen.items():
        if datos["llamadas"] == 0:
            lineas.append(f"<b>{periodo}</b>: nada")
            continue
        lineas.append(
            f"<b>{periodo}</b>: {format_cost(datos['coste'])} "
            f"· {int(datos['llamadas'])} llamadas "
            f"· {int(datos['entrada']):,} tokens dentro, "
            f"{int(datos['salida']):,} fuera".replace(",", ".")
        )

    por_operacion = log.by_operation()
    if por_operacion:
        lineas.append("")
        lineas.append("<i>En que se va:</i>")
        for fila in por_operacion:
            lineas.append(
                f"  {fila['operation']}: {format_cost(fila['coste'] or 0)} "
                f"({fila['llamadas']} llamadas)"
            )

    lineas.append("")
    lineas.append(
        "<i>Estimado con los precios publicos. El cargo real esta en console.anthropic.com.</i>"
    )
    await _reply_long(update, "\n".join(lineas))


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    numbers = _container(context).repository.stats()
    lines = [f"{key}: <b>{value}</b>" for key, value in numbers.items()]
    await _reply_long(update, "📊 <b>Historial</b>\n" + "\n".join(lines))


async def _documents_for(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    raw: str,
    *,
    want_cover: bool,
    want_summary: bool,
) -> None:
    message = update.effective_message
    if message is None:
        return

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
    except Exception:  # noqa: BLE001 - the bot must not die over one odd posting
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
    """A bare link, or the text of a posting, triggers manual mode."""
    message = update.effective_message
    if message is None:
        return

    text = message.text or ""
    if extract_url(text) is None and len(text) < 200:
        await message.reply_text(
            "Mandame el enlace de una oferta, o pega su texto. /ayuda para lo demas."
        )
        return
    await _documents_for(update, context, text, want_cover=True, want_summary=True)


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The 'Cover letter' and 'Summary' buttons on the alerts."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    # Telegram delivers the button's message as "inaccessible" when it is very
    # old or the bot can no longer read it. You cannot reply on it then, so the
    # answer goes through the chat instead.
    message = query.message if isinstance(query.message, Message) else None
    chat_id = query.message.chat.id if query.message is not None else None

    async def responder(text: str, **kwargs) -> None:
        if message is not None:
            await message.reply_text(text, **kwargs)
        elif chat_id is not None:
            await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)

    action, _, prefix = (query.data or "").partition(":")
    container = _container(context)
    stored = container.repository.find_by_fingerprint_prefix(prefix)
    if stored is None:
        await responder("Esa oferta ya no esta en el historial.")
        return

    if message is not None:
        await message.chat.send_action(ChatAction.TYPING)
    try:
        documents = await container.write_use_case().from_offer(stored.offer)
    except Exception:  # noqa: BLE001
        logger.exception("Fallo generando documentos desde un boton")
        await responder("No he podido generar los documentos.")
        return

    cover, summary = _format_documents(stored.offer, documents)
    body = cover if action == "cover" else summary
    for start in range(0, len(body), TELEGRAM_LIMIT):
        await responder(
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

        horario = container.criteria.schedule
        if horario.enabled and application.job_queue is not None:
            application.job_queue.run_repeating(
                scheduled_search,
                interval=timedelta(hours=horario.every_hours),
                first=timedelta(minutes=horario.first_run_after_minutes),
                name=SEARCH_JOB,
            )
            logger.info(
                "Bot listo. Buscara cada %s h; la primera en %s min.",
                horario.every_hours,
                horario.first_run_after_minutes,
            )
        elif horario.enabled:
            logger.warning(
                "Busqueda automatica pedida pero sin JobQueue. Instala: "
                'pip install "python-telegram-bot[job-queue]"'
            )
        else:
            logger.info("Bot listo. Sin busqueda automatica (schedule.enabled: false).")

    async def post_shutdown(_application: Application) -> None:
        await container.__aexit__(None, None, None)

    application = (
        Application.builder().token(token).post_init(post_init).post_shutdown(post_shutdown).build()
    )

    # Your chat only. Without this, anyone who finds the bot burns your
    # Anthropic quota generating letters.
    only_me = filters.Chat(chat_id=int(chat_id))

    application.add_handler(CommandHandler(["start", "ayuda", "help"], start, filters=only_me))
    application.add_handler(CommandHandler("buscar", search_now, filters=only_me))
    application.add_handler(CommandHandler("top", top_pending, filters=only_me))
    application.add_handler(CommandHandler("stats", stats, filters=only_me))
    application.add_handler(CommandHandler("usage", usage, filters=only_me))
    application.add_handler(CommandHandler("proxima", next_run, filters=only_me))
    application.add_handler(CommandHandler("oferta", offer_command, filters=only_me))
    application.add_handler(CommandHandler("carta", cover_command, filters=only_me))
    application.add_handler(CommandHandler("summary", summary_command, filters=only_me))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & only_me, free_text))
    return application


def run_bot() -> None:
    build_application().run_polling(allowed_updates=Update.ALL_TYPES)
