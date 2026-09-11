"""Renovar la sesion de un portal desde un navegador real.

Dos modos, y el orden importa:

1. Si el perfil del navegador ya tiene la sesion viva (lo normal a partir de
   la primera vez), no hace falta ni contrasena: se abre la pagina, se
   comprueba que sigues dentro y se exportan las cookies.
2. Si la sesion ha caducado, intenta el formulario con las credenciales de
   .env. Si el portal pide captcha o 2FA, para y te deja entrar tu.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from ..adapters.browser import PORTALS, BrowserSession
from ..adapters.cookie_store import CookieStore

logger = logging.getLogger(__name__)


def _is_window_closed(exc: Exception) -> bool:
    """Si cerraste la ventana, Playwright lanza esto. No es un fallo nuestro.

    Se mira por nombre y por mensaje porque `TargetClosedError` no esta
    exportado en todas las versiones de Playwright.
    """
    if type(exc).__name__ in {"TargetClosedError", "TimeoutError"}:
        return True
    message = str(exc).lower()
    return "has been closed" in message or "target closed" in message


@dataclass(frozen=True, slots=True)
class LoginResult:
    source: str
    ok: bool
    detail: str
    expires_at: datetime | None = None


class UnknownPortal(ValueError):
    """El portal no admite sesion, o no existe."""


class RefreshSessions:
    def __init__(
        self,
        *,
        cookie_store: CookieStore,
        profile_dir,
        credentials: dict[str, tuple[str, str]],
    ) -> None:
        self._store = cookie_store
        self._profile_dir = profile_dir
        self._credentials = credentials

    async def refresh(
        self,
        source: str,
        *,
        headless: bool = False,
        auto: bool = False,
        confirm=None,
    ) -> LoginResult:
        """Renueva una sesion.

        `confirm` es la funcion que espera a que termines de entrar a mano.
        En el CLI es un input(); en un test, una lambda.
        """
        portal = PORTALS.get(source)
        if portal is None:
            raise UnknownPortal(
                f"{source} no usa sesion. Portales con cuenta: {', '.join(sorted(PORTALS))}"
            )

        async with BrowserSession(self._profile_dir, headless=headless) as browser:
            try:
                page = await browser.open(portal["login_url"])
                logged_in = await self._ensure_logged_in(
                    browser, page, source, portal, auto=auto, headless=headless, confirm=confirm
                )
                if not logged_in:
                    return LoginResult(source, False, "no se completo el login")

                header, expires_at = await browser.cookie_header(portal["cookie_domain"])
                if not header:
                    return LoginResult(
                        source,
                        False,
                        "no hay cookies de ese dominio: el login fue en otro navegador",
                    )

                cookie = self._store.save(source, header, expires_at)
                return LoginResult(source, True, cookie.describe(), expires_at)
            except Exception as exc:  # noqa: BLE001
                if not _is_window_closed(exc):
                    raise
                # Cerrar la ventana antes de guardar es un final normal, no un
                # fallo del programa: no tiene sentido escupir un traceback.
                return LoginResult(
                    source,
                    False,
                    "cerraste la ventana antes de guardar la sesion",
                )

    async def _ensure_logged_in(
        self, browser, page, source, portal, *, auto, headless, confirm
    ) -> bool:
        if await self._looks_logged_in(page, portal):
            logger.info("%s: el perfil ya tenia la sesion abierta", source)
            return True

        if auto:
            credentials = self._credentials.get(source)
            if credentials is None:
                logger.warning(
                    "%s: pediste --auto pero faltan %s_USER y %s_PASSWORD en .env",
                    source,
                    source.upper(),
                    source.upper(),
                )
            else:
                user, password = credentials
                if await browser.try_form_login(page, user, password):
                    return True

        if headless:
            # Sin ventana no hay forma de resolver un captcha ni un 2FA.
            logger.error(
                "%s: la sesion caduco y en modo headless no puedo pedirte que entres. "
                "Ejecuta `jobbot login %s` sin --headless.",
                source,
                source,
            )
            return False

        if confirm is None:
            return False
        confirm(source)
        return True

    @staticmethod
    async def _looks_logged_in(page, portal) -> bool:
        """Heuristica: si el portal no te ha mandado a su pantalla de login,
        es que sigues dentro."""
        url = page.url.lower()
        if any(marker in url for marker in ("login", "signin", "sign-in", "acceso")):
            return False
        return portal["logged_in_hint"] in url or "login" not in url
