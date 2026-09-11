"""Huella de una oferta, para no avisarte dos veces de lo mismo.

La misma oferta aparece en LinkedIn, en InfoJobs y en la web de la empresa con
titulos ligeramente distintos. La huella normaliza empresa + puesto para que
las tres colapsen en una sola.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

from .models import JobOffer

# Ruido que las empresas meten en el titulo y que no distingue una oferta de otra.
_TITLE_NOISE = (
    r"\((?:remote|remoto|híbrido|hibrido|presencial|h/m/x|m/f/d|f/m/d|m/w/d)\)",
    r"\b(?:100%\s*)?(?:remote|remoto|teletrabajo|híbrido|hibrido)\b",
    r"\b(?:h/m|m/f|f/m|d/f/m|x/f/m)\b",
    r"\b(?:madrid|barcelona|valencia|sevilla|bilbao|spain|españa|espana|eu|emea)\b",
    r"\b(?:urgente|nueva|new|hiring|contratamos)\b",
    r"[|·–—-]+\s*$",
)

# Se aplica ANTES de quitar la puntuacion: "S.L." tiene que seguir siendo una
# sola pieza, o al limpiar los puntos se convierte en "s l" y ya no casa.
# Las alternativas largas van primero (corp antes que co).
_COMPANY_SUFFIXES = re.compile(
    r"\b(?:"
    r"s\.?\s?l\.?\s?u?|s\.?\s?a\.?\s?u?|"
    r"technologies|technology|solutions|consulting|"
    r"corp(?:oration)?|group|grupo|gmbh|"
    r"inc|ltd|llc|plc|b\.?v|n\.?v|co|tech|"
    r"spain|espana|iberia"
    r")\b\.?",
)


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_title(title: str) -> str:
    text = _strip_accents(title).lower()
    for pattern in _TITLE_NOISE:
        text = re.sub(pattern, " ", text)
    text = re.sub(r"[^a-z0-9+#\s]", " ", text)
    tokens = sorted(set(text.split()))
    return " ".join(tokens)


def normalize_company(company: str) -> str:
    text = _strip_accents(company).lower()
    stripped = _COMPANY_SUFFIXES.sub(" ", text)
    stripped = " ".join(re.sub(r"[^a-z0-9\s]", " ", stripped).split())
    if stripped:
        return stripped
    # Una empresa que se llame literalmente "Tech" se quedaria sin nombre y
    # colisionaria con cualquier otra del mismo puesto.
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", text).split())


def fingerprint(offer: JobOffer) -> str:
    """Identidad estable de una oferta, independiente de la fuente."""
    key = f"{normalize_company(offer.company)}::{normalize_title(offer.title)}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()  # noqa: S324 - no es criptografia


def url_key(url: str) -> str:
    """Segunda huella, por URL canonica, para pillar reposts de la misma fuente."""
    canonical = re.sub(r"[?#].*$", "", url.strip().lower().rstrip("/"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()  # noqa: S324
