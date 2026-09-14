"""Raiz de composicion: el unico sitio donde se decide quien implementa que."""

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
    """Para `--dry-run`: deja probar la busqueda sin tener Telegram montado."""

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
    # httpx logea cada peticion en INFO y ensucia la salida.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


class Container:
    """Monta el grafo de objetos y se encarga de cerrarlo."""

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
        """Los criterios del YAML, con lo que diga .env por encima.

        El sueldo vive en .env a proposito: config.yaml se publica en el repo
        y ahi tus cifras de negociacion no pintan nada.
        """
        criteria = Criteria.load(self.settings.config_path)
        if self.settings.salary_minimum is not None:
            criteria.salary.minimum = self.settings.salary_minimum
        if self.settings.salary_target is not None:
            criteria.salary.target = self.settings.salary_target
        return criteria

    def effective_cookies(self) -> dict[str, str]:
        """Las cookies que se van a usar de verdad.

        Las de `jobbot login` mandan sobre las pegadas a mano en .env: son las
        unicas que el bot sabe refrescar, asi que una manual antigua no debe
        tapar una recien renovada. `jobbot cookies` dice de donde sale cada una.
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
        """Sin ANTHROPIC_API_KEY el bot sigue funcionando, pero solo con
        el scoring por reglas y sin cover letters."""
        if not self.settings.anthropic_api_key:
            if required:
                self.settings.require_anthropic()
            logger.warning("Sin ANTHROPIC_API_KEY: scoring solo por reglas")
            return None
        return AnthropicWriter(self.settings.anthropic_api_key, usage_log=self.usage)

    def reader(self) -> HtmlOfferReader:
        return HtmlOfferReader(self.http)

    def reload_criteria(self) -> bool:
        """Relee config.yaml. Devuelve si algo cambio.

        Sin esto, tocar los criterios obligaba a reiniciar el bot, y es
        precisamente lo que mas se toca. Un fichero mal escrito no tumba al
        bot: se queda con los criterios que ya tenia y avisa.
        """
        try:
            nuevos = self._load_criteria()
        except Exception:  # noqa: BLE001 - un yaml roto no puede parar la busqueda
            logger.exception("config.yaml no se puede leer; sigo con los criterios anteriores")
            return False

        if nuevos == self.criteria:
            return False
        self.criteria = nuevos
        logger.info("config.yaml recargado")
        return True

    def sources(self, criteria: Criteria | None = None):
        """Las fuentes activas, ya con cookies y perfil de navegador.

        Un unico sitio donde se montan: cuando esto vivia duplicado en el CLI,
        a `check-sources` se le olvido pasar el perfil y Otta no arrancaba.
        """
        return build_sources(
            self.http,
            criteria or self.criteria,
            self.effective_cookies(),
            str(self.settings.browser_profile_path),
        )

    def search_use_case(self, *, use_llm: bool = True, notify: bool = True) -> SearchJobs:
        # Cada busqueda arranca con los criterios que haya ahora en disco.
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
