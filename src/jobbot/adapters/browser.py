"""Navegador real para renovar sesiones.

Por que hace falta: los cuatro portales con cuenta protegen tambien el login.
Un POST con usuario y contrasena desde `httpx` se choca con reCAPTCHA, con
detectores de cliente o, en el caso de Welcome to the Jungle, con un reto de
AWS WAF que solo se resuelve ejecutando JavaScript. Un Chromium de verdad los
pasa porque *es* un navegador.

El truco esta en el perfil persistente. La primera vez abres la ventana y
entras tu, con tu 2FA y tus captchas si los hay. A partir de ahi el perfil
guarda la sesion en disco durante semanas, y refrescar las cookies ya no
necesita ni contrasena.

Playwright es opcional: si no esta instalado, todo lo demas del bot funciona
igual. Se instala con:

    pip install -e ".[browser]"
    playwright install chromium
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

logger = logging.getLogger(__name__)

# Donde entrar en cada portal y con que dominio se queda la cookie.
PORTALS = {
    "infojobs": {
        "login_url": "https://www.infojobs.net/candidate/profile/index.xhtml",
        "cookie_domain": "infojobs.net",
        "logged_in_hint": "candidate",
    },
    "glassdoor": {
        "login_url": "https://www.glassdoor.es/profile/login_input.htm",
        "cookie_domain": "glassdoor.es",
        "logged_in_hint": "member",
    },
    "linkedin": {
        "login_url": "https://www.linkedin.com/login",
        "cookie_domain": "linkedin.com",
        "logged_in_hint": "feed",
    },
    "otta": {
        "login_url": "https://app.welcometothejungle.com/",
        "cookie_domain": "welcometothejungle.com",
        "logged_in_hint": "jobs",
    },
}

# El navegador tarda en pintar una SPA; sin esta espera se lee una pagina vacia.
RENDER_WAIT_MS = 7000


class BrowserUnavailable(RuntimeError):
    """Playwright no esta instalado, o falta el binario de Chromium."""


def require_playwright():
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise BrowserUnavailable(
            "Falta Playwright. Instalalo con:\n"
            '    pip install -e ".[browser]"\n'
            "    playwright install chromium"
        ) from exc
    return async_playwright


class BrowserSession:
    """Chromium con perfil persistente.

    El perfil vive en `data/browser-profile/` y es lo que hace que no tengas
    que volver a loguearte cada vez. Tratalo como una sesion abierta de tu
    navegador: quien copie esa carpeta entra en tus cuentas.
    """

    def __init__(
        self,
        profile_dir: str | Path,
        *,
        headless: bool = True,
        locale: str = "es-ES",
    ) -> None:
        self.profile_dir = Path(profile_dir)
        self.headless = headless
        self.locale = locale
        self.channel: str | None = None
        self._playwright = None
        self._context = None

    async def __aenter__(self) -> BrowserSession:
        async_playwright = require_playwright()
        self.profile_dir.mkdir(parents=True, exist_ok=True)

        self._playwright = await async_playwright().start()
        # Chrome de verdad primero. Google bloquea el inicio de sesion en
        # navegadores que detecta como automatizados ("este navegador puede no
        # ser seguro"), y con el Chromium de Playwright pasa a menudo. Con el
        # Chrome instalado y sin la bandera de automatizacion, no.
        for channel in ("chrome", "msedge", None):
            try:
                self._context = await self._playwright.chromium.launch_persistent_context(
                    str(self.profile_dir),
                    channel=channel,
                    headless=self.headless,
                    locale=self.locale,
                    viewport={"width": 1440, "height": 900},
                    args=["--disable-blink-features=AutomationControlled"],
                    ignore_default_args=["--enable-automation"],
                )
            except Exception:  # noqa: BLE001 - probamos el siguiente canal
                continue
            self.channel = channel or "chromium"
            logger.debug("Navegador arrancado con el canal %s", self.channel)
            return self

        raise BrowserUnavailable(
            "No pude arrancar ningun navegador. Prueba: playwright install chromium"
        )

    @property
    def is_open(self) -> bool:
        """False si has cerrado la ventana a mano."""
        return self._context is not None and not getattr(self._context, "_closed", False)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    @property
    def context(self):
        if self._context is None:
            raise BrowserUnavailable("BrowserSession usado fuera de su context manager")
        return self._context

    async def open(self, url: str, *, wait_ms: int = RENDER_WAIT_MS):
        """Abre una pagina y espera a que la SPA termine de pintar."""
        page = await self.context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(wait_ms)
        return page

    async def fetch_html(self, url: str, *, wait_ms: int = RENDER_WAIT_MS) -> str:
        """El HTML ya renderizado, para las fuentes que no se dejan leer de otra forma."""
        page = await self.open(url, wait_ms=wait_ms)
        try:
            # Un scroll dispara la carga diferida de la mayoria de listados.
            await page.mouse.wheel(0, 4000)
            await page.wait_for_timeout(2000)
            return await page.content()
        finally:
            await page.close()

    async def cookie_header(self, domain: str) -> tuple[str, datetime | None]:
        """Las cookies del dominio, ya montadas para la cabecera `Cookie`.

        Devuelve tambien la caducidad mas cercana, que es cuando la sesion
        dejara de valer.
        """
        cookies = await self.context.cookies()
        relevant = [
            cookie for cookie in cookies if domain in (cookie.get("domain") or "").lstrip(".")
        ]
        if not relevant:
            return "", None

        header = "; ".join(f"{cookie['name']}={cookie['value']}" for cookie in relevant)

        expiries = [
            datetime.fromtimestamp(cookie["expires"], tz=UTC)
            for cookie in relevant
            # -1 significa cookie de sesion: muere al cerrar el navegador.
            if cookie.get("expires", -1) and cookie["expires"] > 0
        ]
        return header, min(expiries) if expiries else None

    async def try_form_login(self, page, user: str, password: str) -> bool:
        """Rellena el formulario de login, si lo encuentra.

        A proposito busca por tipo de campo y no por identificadores concretos:
        los portales renombran sus ids cada dos por tres, pero un formulario de
        login sigue teniendo un campo de email y uno de contrasena.

        Devuelve False cuando no encuentra el formulario o cuando aparece un
        captcha: en ese caso te toca entrar a mano, que para eso la ventana
        esta abierta.
        """
        email_field = page.locator(
            'input[type="email"], input[name*="email" i], input[id*="email" i], '
            'input[name*="user" i]'
        ).first
        password_field = page.locator('input[type="password"]').first

        try:
            await email_field.wait_for(state="visible", timeout=15_000)
            await password_field.wait_for(state="visible", timeout=5_000)
        except Exception:  # noqa: BLE001 - cualquier fallo aqui significa "hazlo tu"
            logger.info("No encontre el formulario de login; entra a mano en la ventana.")
            return False

        await email_field.fill(user)
        await password_field.fill(password)
        await password_field.press("Enter")
        await page.wait_for_timeout(RENDER_WAIT_MS)

        content = (await page.content()).lower()
        if any(marker in content for marker in ("captcha", "recaptcha", "verificacion", "verify")):
            logger.warning("El portal ha pedido verificacion. Resuelvela en la ventana.")
            return False
        return True
