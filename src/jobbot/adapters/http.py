"""Cliente HTTP compartido por todos los scrapers.

Los portales de empleo cortan el grifo en cuanto notan trafico automatico, asi
que aqui van el user-agent de navegador, el throttle por host y el reintento
con backoff. Un scraper que no encuentra nada devuelve [], nunca revienta.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import defaultdict
from typing import Any

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

BASE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class HttpError(RuntimeError):
    """La peticion fallo despues de agotar los reintentos."""


class HttpClient:
    """Wrapper fino sobre httpx con throttle por dominio y reintentos."""

    def __init__(
        self,
        *,
        timeout: float = 25.0,
        retries: int = 2,
        min_interval: float = 1.5,
        concurrency: int = 4,
    ) -> None:
        self._timeout = timeout
        self._retries = retries
        self._min_interval = min_interval
        self._semaphore = asyncio.Semaphore(concurrency)
        self._last_call: dict[str, float] = defaultdict(float)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> HttpClient:
        self._client = httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            headers=BASE_HEADERS,
        )
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _throttle(self, host: str) -> None:
        """Espacia las peticiones a un mismo host, con jitter."""
        async with self._locks[host]:
            elapsed = time.monotonic() - self._last_call[host]
            wait = self._min_interval - elapsed
            if wait > 0:
                await asyncio.sleep(wait + random.uniform(0, 0.3))
            self._last_call[host] = time.monotonic()

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        if self._client is None:
            raise HttpError("HttpClient usado fuera de su context manager")

        host = httpx.URL(url).host
        last_error: Exception | None = None

        for attempt in range(self._retries + 1):
            await self._throttle(host)
            async with self._semaphore:
                try:
                    response = await self._client.get(url, params=params, headers=headers)
                except httpx.HTTPError as exc:
                    last_error = exc
                    logger.debug("GET %s fallo (%s), intento %s", url, exc, attempt + 1)
                else:
                    if response.status_code in RETRYABLE_STATUS:
                        last_error = HttpError(f"{response.status_code} en {url}")
                        logger.debug("GET %s -> %s, reintentando", url, response.status_code)
                    elif response.status_code >= 400:
                        raise HttpError(f"{response.status_code} en {url}")
                    else:
                        return response

            if attempt < self._retries:
                await asyncio.sleep(2**attempt + random.uniform(0, 0.5))

        raise HttpError(f"GET {url} agoto los reintentos: {last_error}")

    async def get_text(self, url: str, **kwargs: Any) -> str:
        response = await self.get(url, **kwargs)
        return response.text

    async def get_json(self, url: str, **kwargs: Any) -> Any:
        headers = {"Accept": "application/json, text/plain, */*"}
        headers.update(kwargs.pop("headers", None) or {})
        response = await self.get(url, headers=headers, **kwargs)
        return response.json()
