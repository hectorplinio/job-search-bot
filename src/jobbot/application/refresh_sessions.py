"""Renewing a job board session from a real browser.

Two modes, and the order matters:

1. If the browser profile still holds a live session (the normal case after
   the first time), no password is needed: open the page, check you are
   still signed in and export the cookies.
2. If the session has expired, try the form with the credentials from .env.
   If the site asks for a captcha or 2FA, stop and let you sign in yourself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from ..adapters.browser import PORTALS, BrowserSession
from ..adapters.cookie_store import CookieStore

logger = logging.getLogger(__name__)


def _is_window_closed(exc: Exception) -> bool:
    """Playwright raises this when you close the window. Not our failure.

    Checked by name and by message because `TargetClosedError` is not
    exported in every version of Playwright.
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
    """The job board takes no session, or does not exist."""


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
        """Renews a session.

        `confirm` is the function that waits until you finish signing in by
        hand. In the CLI it is an input(); in a test, a lambda.
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
                # Closing the window before saving is a normal ending, not a
                # program failure: printing a traceback makes no sense.
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
            # With no window there is no way to solve a captcha or a 2FA step.
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
        """Heuristic: if the site has not bounced you to its login screen,
        you are still signed in."""
        url = page.url.lower()
        if any(marker in url for marker in ("login", "signin", "sign-in", "acceso")):
            return False
        return portal["logged_in_hint"] in url or "login" not in url
