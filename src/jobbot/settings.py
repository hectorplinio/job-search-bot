"""Settings that come from the environment (.env), kept apart from criteria."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class MissingSetting(RuntimeError):
    """A required environment variable is missing."""


# Sources that can use your session. The cookie is read from <NAME>_COOKIE
# and lives only in .env: never in config.yaml, which does go to git.
COOKIE_CAPABLE_SOURCES = ("infojobs", "glassdoor", "linkedin", "otta")


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    anthropic_api_key: str | None
    db_path: Path
    config_path: Path
    profile_path: Path
    log_level: str
    source_cookies: dict[str, str]
    cookie_path: Path
    browser_profile_path: Path
    source_credentials: dict[str, tuple[str, str]]
    # What you do not want published in config.yaml. Empty = the YAML wins.
    salary_minimum: int | None
    salary_target: int | None

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv(PROJECT_ROOT / ".env")

        def path_of(env_name: str, default: str) -> Path:
            raw = os.getenv(env_name, default)
            candidate = Path(raw)
            return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate

        return cls(
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
            db_path=path_of("JOBBOT_DB_PATH", "data/jobs.sqlite3"),
            config_path=path_of("JOBBOT_CONFIG_PATH", "config.yaml"),
            profile_path=path_of("JOBBOT_PROFILE_PATH", "profile/cv.yaml"),
            log_level=os.getenv("JOBBOT_LOG_LEVEL", "INFO").upper(),
            source_cookies=cls._read_cookies(),
            cookie_path=path_of("JOBBOT_COOKIE_PATH", "data/cookies.json"),
            browser_profile_path=path_of("JOBBOT_BROWSER_PROFILE", "data/browser-profile"),
            source_credentials=cls._read_credentials(),
            salary_minimum=cls._read_int("JOBBOT_SALARY_MINIMUM"),
            salary_target=cls._read_int("JOBBOT_SALARY_TARGET"),
        )

    @staticmethod
    def _read_int(name: str) -> int | None:
        """A malformed value must not take the bot down: ignore it and warn."""
        raw = (os.getenv(name) or "").strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            logger.warning("%s no es un numero (%r); se usa el valor de config.yaml", name, raw)
            return None

    @staticmethod
    def _read_cookies() -> dict[str, str]:
        cookies = {}
        for name in COOKIE_CAPABLE_SOURCES:
            raw = (os.getenv(f"{name.upper()}_COOKIE") or "").strip()
            if raw:
                cookies[name] = raw
        return cookies

    @staticmethod
    def _read_credentials() -> dict[str, tuple[str, str]]:
        """Username and password per job board, only for the automatic login."""
        credentials = {}
        for name in COOKIE_CAPABLE_SOURCES:
            user = (os.getenv(f"{name.upper()}_USER") or "").strip()
            password = os.getenv(f"{name.upper()}_PASSWORD") or ""
            if user and password:
                credentials[name] = (user, password)
        return credentials

    def require_telegram(self) -> tuple[str, str]:
        if not self.telegram_bot_token or not self.telegram_chat_id:
            raise MissingSetting(
                "Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID. Copia .env.example a .env."
            )
        return self.telegram_bot_token, self.telegram_chat_id

    def require_anthropic(self) -> str:
        if not self.anthropic_api_key:
            raise MissingSetting(
                "Falta ANTHROPIC_API_KEY. Sin ella no hay cover letters ni scoring con LLM."
            )
        return self.anthropic_api_key
