"""Pieces shared by every public-sector scraper. Mirrors
adapters/sources/base.py - same `safe_search` contract, same reasoning: one
broken source must not take the whole run down with it."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import date

from ...domain.criteria import PublicCriteria
from ...domain.public_models import Oposicion
from ..http import HttpClient

logger = logging.getLogger(__name__)


class PublicBaseSource(ABC):
    """The shared contract: `search` may fail, `safe_search` may not."""

    name: str = "base"

    def __init__(self, http: HttpClient, options: dict | None = None) -> None:
        self.http = http
        self.options = options or {}

    @abstractmethod
    async def search(self, criteria: PublicCriteria, *, on: date | None = None) -> list[Oposicion]:
        """The concrete implementation. It may raise."""

    async def safe_search(
        self, criteria: PublicCriteria, *, on: date | None = None
    ) -> list[Oposicion]:
        """What the use case calls. A source that is down does not sink the run."""
        try:
            items = await self.search(criteria, on=on)
        except Exception:  # noqa: BLE001 - one broken source must not stop the others
            logger.exception("Public source %s failed; skipping it on this run", self.name)
            return []
        logger.info("%s: %s vacantes", self.name, len(items))
        return items
