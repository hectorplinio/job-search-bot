"""A real browser, for renewing sessions.

Why it is needed: the four job boards with an account protect their login as
well. A POST with username and password from `httpx` runs into reCAPTCHA, into
client fingerprinting or, in the case of Welcome to the Jungle, into an AWS WAF
challenge that is only solved by executing JavaScript. A real Chromium gets
through because it *is* a browser.

The trick is the persistent profile. The first time you open the window and
sign in yourself, with your 2FA and your captchas if there are any. From then
on the profile keeps the session on disk for weeks, and refreshing the cookies
needs no password at all.

Playwright is optional: if it is not installed, everything else in the bot
works the same. Install it with:

    pip install -e ".[browser]"
    playwright install chromium
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

logger = logging.getLogger(__name__)

# Where to sign in on each board, and which domain the cookie belongs to.
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

# A browser takes time to paint a SPA; without this wait you read a blank page.
RENDER_WAIT_MS = 7000


class BrowserUnavailable(RuntimeError):
    """Playwright is not installed, or the Chromium binary is missing."""


def require_playwright():
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise BrowserUnavailable(
            "Falta Playwright. Instalalo con:\n"
            '    pip install -e ".[browser]"\n'
            "    playwright install chromium"
        ) from exc
    return async_playwright


class BrowserSession:
    """Chromium with a persistent profile.

    The profile lives in `data/browser-profile/` and is what saves you from
    signing in again every time. Treat it like an open browser session:
    whoever copies that folder gets into your accounts.
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
        if self._playwright is None:  # pragma: no cover - does not happen in practice
            raise RuntimeError("Playwright no ha arrancado; revisa la instalacion")
        # Real Chrome first. Google blocks sign-in on browsers it detects as
        # automated ("this browser may not be secure"), which happens often
        # with Playwright's Chromium. With the installed Chrome and no
        # automation flag, it does not.
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
            except Exception:  # noqa: BLE001 - try the next channel
                continue
            self.channel = channel or "chromium"
            logger.debug("Browser started on channel %s", self.channel)
            return self

        raise BrowserUnavailable(
            "No pude arrancar ningun navegador. Prueba: playwright install chromium"
        )

    @property
    def is_open(self) -> bool:
        """False if you closed the window by hand."""
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
        """Opens a page and waits for the SPA to finish painting."""
        page = await self.context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(wait_ms)
        return page

    async def fetch_html(self, url: str, *, wait_ms: int = RENDER_WAIT_MS) -> str:
        """The rendered HTML, for sources that cannot be read any other way."""
        page = await self.open(url, wait_ms=wait_ms)
        try:
            # A scroll triggers the lazy loading most listings use.
            await page.mouse.wheel(0, 4000)
            await page.wait_for_timeout(2000)
            return await page.content()
        finally:
            await page.close()

    async def cookie_header(self, domain: str) -> tuple[str, datetime | None]:
        """The domain cookies, already assembled for the `Cookie` header.

        It also returns the nearest expiry, which is when the session stops
        being valid.
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
            # -1 means a session cookie: it dies when the browser closes.
            if cookie.get("expires", -1) and cookie["expires"] > 0
        ]
        return header, min(expiries) if expiries else None

    async def try_form_login(self, page, user: str, password: str) -> bool:
        """Fills in the login form, if it finds one.

        It deliberately looks for field types rather than specific identifiers:
        job boards rename their ids constantly, but a login form still has an
        email field and a password field.

        Returns False when it cannot find the form or when a captcha shows up:
        then it is on you to sign in by hand, which is what the open window is
        for.
        """
        email_field = page.locator(
            'input[type="email"], input[name*="email" i], input[id*="email" i], '
            'input[name*="user" i]'
        ).first
        password_field = page.locator('input[type="password"]').first

        try:
            await email_field.wait_for(state="visible", timeout=15_000)
            await password_field.wait_for(state="visible", timeout=5_000)
        except Exception:  # noqa: BLE001 - any failure here means "do it yourself"
            logger.info("Could not find the login form; sign in by hand in the window.")
            return False

        await email_field.fill(user)
        await password_field.fill(password)
        await password_field.press("Enter")
        await page.wait_for_timeout(RENDER_WAIT_MS)

        content = (await page.content()).lower()
        if any(marker in content for marker in ("captcha", "recaptcha", "verificacion", "verify")):
            logger.warning("The site asked for verification. Solve it in the window.")
            return False
        return True
