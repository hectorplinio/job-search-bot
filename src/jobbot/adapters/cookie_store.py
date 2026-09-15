"""On-disk store for session cookies.

Cookies expire. Instead of pasting them into .env by hand every time,
`jobbot login` refreshes them from a real browser and leaves them here, with
whatever expiry date the site itself reports.

The file is as sensitive as your password: it lives in `data/`, which is in
.gitignore, and it is never printed in full to the screen or the logs.
"""

from __future__ import annotations

import contextlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StoredCookie:
    source: str
    value: str
    saved_at: datetime
    expires_at: datetime | None

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= datetime.now(UTC)

    @property
    def age_days(self) -> int:
        return (datetime.now(UTC) - self.saved_at).days

    def describe(self) -> str:
        """A summary that is safe to print: it never includes the value."""
        if self.expires_at is None:
            return f"guardada hace {self.age_days} d, sin caducidad declarada"
        if self.is_expired:
            return f"caducada el {self.expires_at:%Y-%m-%d}"
        remaining = (self.expires_at - datetime.now(UTC)).days
        return f"valida {remaining} d mas (hasta {self.expires_at:%Y-%m-%d})"


class CookieStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, StoredCookie]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            logger.warning("No pude leer %s; lo ignoro", self.path.name)
            return {}

        cookies: dict[str, StoredCookie] = {}
        for source, entry in raw.items():
            try:
                cookies[source] = StoredCookie(
                    source=source,
                    value=entry["value"],
                    saved_at=datetime.fromisoformat(entry["saved_at"]),
                    expires_at=(
                        datetime.fromisoformat(entry["expires_at"])
                        if entry.get("expires_at")
                        else None
                    ),
                )
            except (KeyError, TypeError, ValueError):
                logger.warning("Entrada corrupta para %s en %s", source, self.path.name)
        return cookies

    def save(self, source: str, value: str, expires_at: datetime | None = None) -> StoredCookie:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        current = self.load()
        cookie = StoredCookie(
            source=source,
            value=value,
            saved_at=datetime.now(UTC),
            expires_at=expires_at,
        )
        current[source] = cookie

        payload = {
            name: {
                "value": item.value,
                "saved_at": item.saved_at.isoformat(),
                "expires_at": item.expires_at.isoformat() if item.expires_at else None,
            }
            for name, item in current.items()
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        # POSIX permissions do not apply on Windows, but they do on Linux/macOS.
        with contextlib.suppress(OSError):
            self.path.chmod(0o600)
        return cookie

    def delete(self, source: str) -> bool:
        current = self.load()
        if source not in current:
            return False
        del current[source]
        payload = {
            name: {
                "value": item.value,
                "saved_at": item.saved_at.isoformat(),
                "expires_at": item.expires_at.isoformat() if item.expires_at else None,
            }
            for name, item in current.items()
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return True

    def usable(self) -> dict[str, str]:
        """Only the cookies still alive, ready for the header."""
        return {
            source: cookie.value for source, cookie in self.load().items() if not cookie.is_expired
        }
