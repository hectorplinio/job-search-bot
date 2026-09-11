"""Registro de fuentes: config.yaml decide cuales se instancian."""

from __future__ import annotations

from collections.abc import Callable

from ...domain.criteria import Criteria
from ..http import HttpClient
from .base import BaseSource
from .companies import CompaniesSource
from .glassdoor import GlassdoorSource
from .himalayas import HimalayasSource
from .infojobs import InfoJobsSource
from .linkedin import LinkedInSource
from .manfred import ManfredSource
from .otta import OttaSource
from .remoteok import RemoteOkSource
from .remotive import RemotiveSource
from .tecnoempleo import TecnoempleoSource
from .weworkremotely import WeWorkRemotelySource

SourceFactory = Callable[[HttpClient, dict], BaseSource]

REGISTRY: dict[str, SourceFactory] = {
    "companies": CompaniesSource,
    "manfred": ManfredSource,
    "linkedin": LinkedInSource,
    "tecnoempleo": TecnoempleoSource,
    "infojobs": InfoJobsSource,
    "glassdoor": GlassdoorSource,
    "remoteok": RemoteOkSource,
    "remotive": RemotiveSource,
    "himalayas": HimalayasSource,
    "weworkremotely": WeWorkRemotelySource,
    "otta": OttaSource,
}


def build_sources(
    http: HttpClient,
    criteria: Criteria,
    cookies: dict[str, str] | None = None,
    browser_profile: str | None = None,
) -> list[BaseSource]:
    """Instancia solo las fuentes marcadas como enabled.

    Las cookies llegan desde .env, no desde config.yaml, y se inyectan aqui
    en las opciones. Asi las fuentes no saben nada de variables de entorno y
    los secretos no acaban en un fichero versionado.
    """
    cookies = cookies or {}
    sources = []
    for name, factory in REGISTRY.items():
        if not criteria.source_enabled(name):
            continue
        options = dict(criteria.source_options(name))
        if cookie := cookies.get(name):
            options["cookie"] = cookie
        if browser_profile:
            options["browser_profile"] = browser_profile
        sources.append(factory(http, options))
    return sources


def available_sources() -> list[str]:
    return sorted(REGISTRY)
