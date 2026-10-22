"""The public-source registry. Mirrors adapters/sources/registry.py."""

from __future__ import annotations

from collections.abc import Callable

from ...domain.criteria import Criteria
from ..http import HttpClient
from .base import PublicBaseSource
from .boe import BoeSource

PublicSourceFactory = Callable[[HttpClient, dict], PublicBaseSource]

PUBLIC_REGISTRY: dict[str, PublicSourceFactory] = {
    "boe": BoeSource,
    # "bopa", "dogv" and "borm" join here once built - same shape, same
    # registry, nothing else changes.
}


def build_public_sources(http: HttpClient, criteria: Criteria) -> list[PublicBaseSource]:
    sources = []
    for name, factory in PUBLIC_REGISTRY.items():
        options = criteria.sources.get(name, {})
        if not options.get("enabled", False):
            continue
        sources.append(factory(http, options))
    return sources
