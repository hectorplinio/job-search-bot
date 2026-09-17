"""Composition root: the only place that decides who implements what."""

from __future__ import annotations

import logging

from .adapters.cookie_store import CookieStore
from .adapters.http import HttpClient
from .adapters.llm.anthropic_writer import AnthropicWriter
from .adapters.offer_reader import HtmlOfferReader
from .adapters.persistence import SqliteOfferRepository
from .adapters.sources.registry import build_sources
from .adapters.telegram_notifier import TelegramNotifier
from .adapters.usage_log import SqliteUsageLog
from .application.search_jobs import SearchJobs
from .application.write_documents import WriteDocuments
from .domain.criteria import Criteria
from .domain.profile import CandidateProfile
from .settings import Settings

logger = logging.getLogger(__name__)


class NullNotifier:
    """For `--dry-run`: lets you try a search without Telegram set up."""

    async def send_offer(self, scored) -> None:
        logger.info("[dry-run] %s/10 %s", scored.score.value, scored.offer.title)

    async def send_text(self, text: str) -> None:
        logger.info("[dry-run] %s", text)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # httpx logs every request at INFO and clutters the output.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


class Container:
    """Builds the object graph and takes care of closing it."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        configure_logging(self.settings.log_level)

        self.criteria = self._load_criteria()
        self.profile = CandidateProfile.load(self.settings.profile_path)
        self.repository = SqliteOfferRepository(self.settings.db_path)
        self.cookies = CookieStore(self.settings.cookie_path)
        self.usage = SqliteUsageLog(self.settings.db_path)
        self._http: HttpClient | None = None

    def _load_criteria(self) -> Criteria:
        """The criteria from the YAML, with .env taking precedence.

        Salary lives in .env on purpose: config.yaml is published in the repo,
        and your negotiating figures have no business being there.
        """
        criteria = Criteria.load(self.settings.config_path)
        if self.settings.salary_minimum is not None:
            criteria.salary.minimum = self.settings.salary_minimum
        if self.settings.salary_target is not None:
            criteria.salary.target = self.settings.salary_target
        return criteria

    def effective_cookies(self) -> dict[str, str]:
        """The cookies that will actually be used.

        The ones from `jobbot login` win over those pasted by hand into .env:
        they are the only ones the bot can refresh, so a stale manual cookie
        must not mask a freshly renewed one. `jobbot cookies` says where each
        one comes from.
        """
        return {**self.settings.source_cookies, **self.cookies.usable()}

    async def __aenter__(self) -> Container:
        self._http = await HttpClient().__aenter__()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._http is not None:
            await self._http.__aexit__(*exc_info)
            self._http = None
        self.repository.close()
        self.usage.close()

    @property
    def http(self) -> HttpClient:
        if self._http is None:
            raise RuntimeError("Container usado fuera de su context manager")
        return self._http

    def notifier(self) -> TelegramNotifier:
        token, chat_id = self.settings.require_telegram()
        return TelegramNotifier(
            token, chat_id, delay_seconds=self.criteria.telegram.delay_between_messages
        )

    def writer(self, *, required: bool = True) -> AnthropicWriter | None:
        """Without ANTHROPIC_API_KEY the bot still works, but only with
        rule-based scoring and no cover letters."""
        if not self.settings.anthropic_api_key:
            if required:
                self.settings.require_anthropic()
            logger.warning("No ANTHROPIC_API_KEY: rule-based scoring only")
            return None
        return AnthropicWriter(self.settings.anthropic_api_key, usage_log=self.usage)

    def reader(self) -> HtmlOfferReader:
        return HtmlOfferReader(self.http)

    def reload_criteria(self) -> bool:
        """Re-reads config.yaml. Returns whether anything changed.

        Without this, touching the criteria meant restarting the bot, and the
        criteria are exactly what you touch most. A malformed file does not
        take the bot down: it keeps the criteria it had and warns.
        """
        try:
            nuevos = self._load_criteria()
        except Exception:  # noqa: BLE001 - a broken yaml must not stop the search
            logger.exception("config.yaml cannot be read; carrying on with the previous criteria")
            return False

        if nuevos == self.criteria:
            return False
        self.criteria = nuevos
        logger.info("config.yaml reloaded")
        return True

    def sources(self, criteria: Criteria | None = None):
        """The enabled sources, wired up with cookies and browser profile.

        One single place where they are built: when this was duplicated in the
        CLI, `check-sources` forgot to pass the profile and Otta never started.
        """
        return build_sources(
            self.http,
            criteria or self.criteria,
            self.effective_cookies(),
            str(self.settings.browser_profile_path),
        )

    def search_use_case(self, *, use_llm: bool = True, notify: bool = True) -> SearchJobs:
        # Every search starts from whatever criteria are on disk right now.
        self.reload_criteria()
        return SearchJobs(
            sources=self.sources(),
            repository=self.repository,
            notifier=self.notifier() if notify else NullNotifier(),
            criteria=self.criteria,
            profile=self.profile,
            writer=self.writer(required=False) if use_llm else None,
        )

    def write_use_case(self) -> WriteDocuments:
        return WriteDocuments(
            reader=self.reader(),
            writer=self.writer(required=True),
            profile=self.profile,
        )
