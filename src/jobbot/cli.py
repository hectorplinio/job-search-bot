"""The command line interface.

jobbot run            one search pass (this is what the cron job runs)
jobbot bot            starts the bot in listening mode
jobbot apply <url>    cover letter + summary for one specific posting
jobbot stats          what the bot has seen so far
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .adapters.cookie_store import CookieStore
from .adapters.sources.registry import available_sources
from .container import Container
from .settings import PROJECT_ROOT, MissingSetting, Settings

app = typer.Typer(add_completion=False, help="Buscador de ofertas con alertas en Telegram.")
console = Console()


def _run(coroutine):
    try:
        return asyncio.run(coroutine)
    except MissingSetting as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc


@app.command()
def run(
    dry_run: bool = typer.Option(False, "--dry-run", help="No manda nada a Telegram."),
    no_llm: bool = typer.Option(False, "--no-llm", help="Solo scoring por reglas, sin gastar."),
    report: bool = typer.Option(True, "--report/--no-report", help="Manda el resumen a Telegram."),
) -> None:
    """One full pass: search, filter, score and alert."""

    async def _main() -> None:
        async with Container() as container:
            use_case = container.search_use_case(use_llm=not no_llm, notify=not dry_run)
            result = await use_case.run(dry_run=dry_run)

            console.print(result.as_text())
            for item in result.alerts:
                console.print(
                    f"  [green]{item.score.value}/10[/green] {item.offer.title} "
                    f"· {item.offer.company} · {item.offer.url}"
                )

            if report and not dry_run and result.notified == 0:
                await container.notifier().send_text(
                    "🔍 Sin ofertas nuevas que encajen esta vez.\n\n" + result.as_text()
                )

    _run(_main())


@app.command()
def bot() -> None:
    """Starts the bot so you can talk to it from Telegram."""
    from .bot import run_bot

    run_bot()


@app.command()
def apply(
    target: str = typer.Argument(..., help="URL de la oferta, o el texto pegado entre comillas."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Carpeta donde guardarlo."),
) -> None:
    """Writes the cover letter and the tailored summary for one posting."""

    async def _main() -> None:
        async with Container() as container:
            offer, documents = await container.write_use_case().from_input(target)

            console.rule(f"{offer.title} · {offer.company or 'empresa no detectada'}")
            console.print("[bold]Stack detectado:[/bold] " + ", ".join(documents.detected_stack))
            console.rule("Cover letter")
            console.print(documents.cover_letter)
            console.rule("CV summary")
            console.print(documents.cv_summary)

            if output is not None:
                output.mkdir(parents=True, exist_ok=True)
                slug = "".join(ch if ch.isalnum() else "-" for ch in offer.title.lower())[:60]
                (output / f"{slug}-cover-letter.txt").write_text(
                    documents.cover_letter, encoding="utf-8"
                )
                (output / f"{slug}-summary.txt").write_text(documents.cv_summary, encoding="utf-8")
                console.print(f"\n[green]Guardado en {output}[/green]")

    _run(_main())


@app.command()
def stats() -> None:
    """What the bot has seen and sent."""

    async def _main() -> None:
        async with Container() as container:
            table = Table("Metrica", "Valor")
            for key, value in container.repository.stats().items():
                table.add_row(key, str(value))
            console.print(table)

    _run(_main())


@app.command()
def usage() -> None:
    """How much you have spent on the Claude API."""

    async def _main() -> None:
        from .domain.cost import format_cost

        async with Container() as container:
            resumen = container.usage.summary()
            table = Table("Periodo", "Coste", "Llamadas", "Tokens dentro", "Tokens fuera")
            for periodo, datos in resumen.items():
                table.add_row(
                    periodo,
                    format_cost(datos["coste"]),
                    str(int(datos["llamadas"])),
                    f"{int(datos['entrada']):,}".replace(",", "."),
                    f"{int(datos['salida']):,}".replace(",", "."),
                )
            console.print(table)

            por_operacion = container.usage.by_operation()
            if por_operacion:
                detalle = Table("En que se va", "Coste", "Llamadas")
                for fila in por_operacion:
                    detalle.add_row(
                        fila["operation"], format_cost(fila["coste"] or 0), str(fila["llamadas"])
                    )
                console.print(detalle)

            console.print(
                "\n[dim]Estimado con los precios publicos de Anthropic. "
                "El cargo real esta en console.anthropic.com.[/dim]"
            )

    _run(_main())


@app.command()
def sources() -> None:
    """Available sources, and which ones are enabled in config.yaml."""

    async def _main() -> None:
        async with Container() as container:
            table = Table("Fuente", "Estado")
            for name in available_sources():
                active = container.criteria.source_enabled(name)
                table.add_row(name, "[green]activa[/green]" if active else "[dim]apagada[/dim]")
            console.print(table)

    _run(_main())


@app.command()
def login(
    source: str | None = typer.Argument(None, help="infojobs, glassdoor, linkedin u otta."),
    auto: bool = typer.Option(
        False, "--auto", help="Rellena el formulario con las credenciales de .env."
    ),
    headless: bool = typer.Option(
        False, "--headless", help="Sin ventana. Solo sirve si la sesion sigue viva."
    ),
) -> None:
    """Renews a job board session by opening a real browser.

    The first time you sign in yourself in the window, with your 2FA if you
    have one. The browser profile keeps the session, and from then on running
    this again is enough to refresh the cookies.
    """

    async def _main() -> None:
        from .adapters.browser import PORTALS, BrowserUnavailable
        from .application.refresh_sessions import RefreshSessions, UnknownPortal

        settings = Settings.from_env()
        targets = [source] if source else sorted(PORTALS)

        use_case = RefreshSessions(
            cookie_store=CookieStore(settings.cookie_path),
            profile_dir=settings.browser_profile_path,
            credentials=settings.source_credentials,
        )

        def wait_for_manual_login(name: str) -> None:
            console.print(
                f"\n[bold]Inicia sesion en {name} DENTRO de la ventana que se ha abierto.[/bold]\n"
                "\n"
                "  · Esa ventana es un navegador aparte, con su propio perfil.\n"
                "  · Si entras en tu Chrome de siempre no sirve: las cookies\n"
                "    se quedan alli y esta ventana no las ve.\n"
                "  · Vale entrar con Google; es Chrome de verdad, no lo bloquea.\n"
                "  · No la cierres hasta que respondas aqui.\n"
            )
            typer.confirm("¿Ya has entrado en esa ventana?", default=True, abort=True)

        table = Table("Portal", "Resultado", "Detalle")
        for name in targets:
            if name == "linkedin":
                console.print(
                    "[yellow]LinkedIn: usar tu cuenta aqui puede costarte el perfil, "
                    "y el endpoint de invitado ya devuelve lo mismo. Ver README.[/yellow]"
                )
                if not typer.confirm(f"¿Renovar {name} de todas formas?", default=False):
                    table.add_row(name, "[dim]omitido[/dim]", "decision tuya")
                    continue
            try:
                result = await use_case.refresh(
                    name, headless=headless, auto=auto, confirm=wait_for_manual_login
                )
            except UnknownPortal as exc:
                table.add_row(name, "[red]error[/red]", str(exc))
                continue
            except BrowserUnavailable as exc:
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(code=1) from exc

            mark = "[green]ok[/green]" if result.ok else "[red]fallo[/red]"
            table.add_row(name, mark, result.detail)

        console.print(table)
        console.print("\n[dim]Comprueba que funciona con: jobbot check-sources[/dim]")

    _run(_main())


@app.command()
def cookies() -> None:
    """The state of the stored sessions. It never prints the cookie value."""

    async def _main() -> None:
        settings = Settings.from_env()
        stored = CookieStore(settings.cookie_path).load()

        table = Table("Portal", "Origen", "Estado")
        for name in sorted(set(stored) | set(settings.source_cookies)):
            if name in stored:
                cookie = stored[name]
                state = "[red]caducada[/red]" if cookie.is_expired else "[green]viva[/green]"
                table.add_row(name, "jobbot login", f"{state} · {cookie.describe()}")
            else:
                table.add_row(name, ".env", "[yellow]sin caducidad conocida[/yellow]")

        if table.row_count == 0:
            console.print("No hay ninguna sesion guardada. Empieza con: jobbot login")
            return
        console.print(table)

    _run(_main())


@app.command(name="check-sources")
def check_sources(
    query: str = typer.Option("python", "--query", "-q", help="Una sola busqueda de prueba."),
) -> None:
    """Tries every enabled source and reports how many postings it returns.

    This is what to run after putting a cookie in .env: if the source goes
    from 0 to a number, the session is working.
    """

    async def _main() -> None:
        async with Container() as container:
            probe = container.criteria.model_copy(deep=True)
            probe.search.queries = [query]
            probe.search.max_results_per_query = 10
            # Per-source options may carry their own list of queries.
            for options in probe.sources.values():
                options.pop("queries", None)

            sources = container.sources(probe)
            if not sources:
                console.print("[yellow]No hay ninguna fuente activa en config.yaml.[/yellow]")
                return

            table = Table("Fuente", "Sesion", "Ofertas", "Veredicto")
            for source in sources:
                offers = await source.safe_search(probe)
                session = "tu cuenta" if source.has_session else "anonima"
                if offers:
                    verdict = "[green]responde[/green]"
                elif source.has_session:
                    verdict = "[red]0 con sesion: cookie caducada o invalida[/red]"
                else:
                    verdict = "[yellow]0: bloqueo o sin resultados[/yellow]"
                table.add_row(source.name, session, str(len(offers)), verdict)

            console.print(table)
            console.print(
                "\n[dim]Una fuente a 0 no rompe nada: las demas siguen. "
                "Mira los logs con JOBBOT_LOG_LEVEL=INFO para el motivo.[/dim]"
            )

    _run(_main())


@app.command(name="chat-id")
def chat_id(
    save: bool = typer.Option(
        False, "--save", help="Escribe el id en .env sin que tengas que copiarlo."
    ),
) -> None:
    """Prints your chat id. Write something to the bot before running it."""

    async def _main() -> None:
        from telegram import Bot

        settings = Settings.from_env()
        if not settings.telegram_bot_token:
            raise MissingSetting("Falta TELEGRAM_BOT_TOKEN en .env")

        bot = Bot(settings.telegram_bot_token)
        me = await bot.get_me()
        updates = await bot.get_updates()

        chats = {
            update.effective_chat.id: update.effective_chat
            for update in updates
            if update.effective_chat is not None
        }
        if not chats:
            console.print(
                f"[yellow]Tu bot es @{me.username}.[/yellow]\n"
                f"Abre https://t.me/{me.username}, pulsa Start o mandale un 'hola', "
                "y vuelve a ejecutar esto."
            )
            return

        for chat in chats.values():
            console.print(f"{chat.id}  ({chat.type}) {chat.full_name or chat.title or ''}")

        if not save:
            console.print("\n[dim]Con --save lo guardo yo en .env.[/dim]")
            return

        if len(chats) > 1:
            console.print(
                "\n[yellow]Hay varios chats. No adivino cual quieres: "
                "copia el que toque a TELEGRAM_CHAT_ID en .env.[/yellow]"
            )
            return

        chosen = next(iter(chats))
        _write_chat_id(chosen)
        console.print(f"\n[green]Guardado TELEGRAM_CHAT_ID={chosen} en .env[/green]")

    _run(_main())


def _write_chat_id(value: int) -> None:
    """Replaces only the chat id line and leaves the rest of .env untouched."""
    # The same .env that Settings loads, not whatever JOBBOT_CONFIG_PATH says.
    env_path = PROJECT_ROOT / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines()

    for index, line in enumerate(lines):
        if line.strip().startswith("TELEGRAM_CHAT_ID="):
            lines[index] = f"TELEGRAM_CHAT_ID={value}"
            break
    else:
        lines.append(f"TELEGRAM_CHAT_ID={value}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    app()
