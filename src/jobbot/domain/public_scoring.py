"""Scoring an oposicion against your priorities, 0 to 100.

Same spirit as scoring.py: a pure function, same input and criteria always
give the same score. The one rule that does not fit that model is urgency -
an open-deadline vacancy in your priority area is ALWAYS notified, score or
no score, because missing a 10-day window is a worse failure mode than one
extra message.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta

from .criteria import PublicCriteria
from .public_models import Ambito, Oposicion, PublicMatchScore, Turno


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize(text: str) -> str:
    """Lowercase, no accents - so 'informática' and 'informatica' are the
    same keyword and config.yaml never has to spell both."""
    return _strip_accents(text).lower()


def contains(haystack: str, term: str) -> bool:
    pattern = r"\b" + re.escape(normalize(term)) + r"\b"
    return bool(re.search(pattern, normalize(haystack)))


_GRUPO_PATTERN = re.compile(r"\bgrupo\s+([ABC][12])\b", re.IGNORECASE)
_SUBGRUPO_PATTERN = re.compile(r"\bsubgrupo\s+([ABC][12])\b", re.IGNORECASE)
_TURNO_LIBRE = re.compile(r"\b(turno libre|acceso libre|sistema general de acceso libre)\b")
_TURNO_INTERNA = re.compile(r"\b(promocion interna|turno de promocion interna)\b")
_BOLSA = re.compile(r"\bbolsa (de empleo|de trabajo)\b")
_INTERINO = re.compile(r"\b(interin[oa]s?|funcionari[oa]s? interin[oa]s?)\b")
_DIAS_HABILES = re.compile(r"\b(\d{1,2})\s*d[ií]as h[aá]biles\b")


def detect_grupo(text: str) -> str | None:
    normalized = normalize(text)
    match = _GRUPO_PATTERN.search(normalized) or _SUBGRUPO_PATTERN.search(normalized)
    return match.group(1).upper() if match else None


def detect_turno(text: str) -> Turno:
    normalized = normalize(text)
    # Interna checked first: "promocion interna" would also match nothing in
    # the libre pattern, but being explicit here avoids relying on order luck.
    if _TURNO_INTERNA.search(normalized):
        return Turno.PROMOCION_INTERNA
    if _TURNO_LIBRE.search(normalized):
        return Turno.LIBRE
    return Turno.DESCONOCIDO


def detect_tipo_plaza(text: str) -> str | None:
    normalized = normalize(text)
    if _BOLSA.search(normalized):
        return "bolsa"
    if _INTERINO.search(normalized):
        return "interino"
    return None


def detect_plazo_dias(text: str) -> int | None:
    match = _DIAS_HABILES.search(normalize(text))
    return int(match.group(1)) if match else None


def business_days_after(start: date, days: int) -> date:
    """Approximate: counts Mon-Fri only, no public-holiday calendar. Good
    enough for a heads-up; always verify the real date on the announcement
    before it matters."""
    current = start
    counted = 0
    while counted < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            counted += 1
    return current


def matches_public_profile(oposicion: Oposicion, criteria: PublicCriteria) -> list[str]:
    text = oposicion.searchable_text
    return [kw for kw in criteria.keywords if contains(text, kw)]


def is_priority_location(oposicion: Oposicion, criteria: PublicCriteria) -> bool:
    text = normalize(f"{oposicion.ubicacion} {oposicion.organismo}")
    return any(contains(text, place) for place in criteria.priority_locations)


def is_relevant_estado_body(oposicion: Oposicion, criteria: PublicCriteria) -> bool:
    """From the Estado (ambito ESTADO), only the configured TIC bodies count.
    Outside the Estado, this check does not apply - local/autonomic calls are
    small enough that the keyword match alone is reliable."""
    if oposicion.ambito != Ambito.ESTADO:
        return True
    text = oposicion.searchable_text
    return any(contains(text, cuerpo) for cuerpo in criteria.estado_cuerpos_tic)


def score_oposicion(oposicion: Oposicion, criteria: PublicCriteria) -> PublicMatchScore:
    matched = matches_public_profile(oposicion, criteria)
    if not matched:
        return PublicMatchScore(value=0, blockers=("no coincide con palabras clave TIC",))

    if not is_relevant_estado_body(oposicion, criteria):
        return PublicMatchScore(
            value=0, blockers=("ambito Estado fuera de los cuerpos TIC configurados",)
        )

    if oposicion.turno == Turno.PROMOCION_INTERNA:
        return PublicMatchScore(
            value=0, blockers=("turno de promocion interna: no accesible desde fuera",)
        )

    priority = is_priority_location(oposicion, criteria)
    reasons = [f"palabras clave: {', '.join(matched)}"]

    points = 40  # base: it is a real TIC match
    points += 10 * min(len(matched), 3)

    if priority:
        points += 30
        reasons.append("ambito geografico prioritario")
    else:
        reasons.append("fuera del ambito geografico prioritario")

    if not oposicion.elegible:
        points -= 15
        reasons.append("NO ELEGIBLE: requiere grado universitario (turno libre, A1/A2)")

    if oposicion.tipo_plaza.value in ("bolsa", "interino"):
        reasons.append("bolsa/interinidad: cubre el expediente, no es plaza fija")
    elif oposicion.tipo_plaza.value == "fija":
        points += 10
        reasons.append("plaza fija")

    urgent = bool(priority and oposicion.elegible and oposicion.plazo_abierto)
    if urgent:
        reasons.append("plazo abierto en ambito prioritario: SIEMPRE se notifica")

    return PublicMatchScore(
        value=max(0, min(100, points)),
        reasons=tuple(reasons),
        urgent=urgent,
    )
