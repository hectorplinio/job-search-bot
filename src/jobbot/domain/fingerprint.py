"""A posting's fingerprint, so you are never alerted twice about the same job.

The same job shows up on LinkedIn, on InfoJobs and on the company's own site
with slightly different titles. The fingerprint normalises company + role so
the three collapse into one.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

from .models import JobOffer

# Noise companies put in titles that does not tell one posting from another.
_TITLE_NOISE = (
    r"\((?:remote|remoto|híbrido|hibrido|presencial|h/m/x|m/f/d|f/m/d|m/w/d)\)",
    r"\b(?:100%\s*)?(?:remote|remoto|teletrabajo|híbrido|hibrido)\b",
    r"\b(?:h/m|m/f|f/m|d/f/m|x/f/m)\b",
    r"\b(?:madrid|barcelona|valencia|sevilla|bilbao|spain|españa|espana|eu|emea)\b",
    r"\b(?:urgente|nueva|new|hiring|contratamos)\b",
    r"[|·–—-]+\s*$",
)

# Applied BEFORE stripping punctuation: "S.L." has to stay one piece, or once
# the dots are gone it becomes "s l" and no longer matches. Longer alternatives
# come first (corp before co).
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
    # A company literally called "Tech" would be left with no name at all and
    # would collide with any other one hiring for the same role.
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", text).split())


def fingerprint(offer: JobOffer) -> str:
    """A posting's stable identity, independent of the source."""
    key = f"{normalize_company(offer.company)}::{normalize_title(offer.title)}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()  # noqa: S324 - not cryptography


def url_key(url: str) -> str:
    """A second fingerprint, by canonical URL, to catch reposts from one source."""
    canonical = re.sub(r"[?#].*$", "", url.strip().lower().rstrip("/"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()  # noqa: S324
