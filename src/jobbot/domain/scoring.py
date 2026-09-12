"""Puntuacion de una oferta contra el perfil, del 1 al 10.

Todo esto es una funcion pura: misma oferta y mismos criterios, misma nota.
El LLM puede afinarla despues, pero nunca resucita una oferta bloqueada aqui.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from functools import lru_cache

from .criteria import Criteria
from .models import JobOffer, MatchScore, WorkMode

SENIOR_MARKERS = ("senior", "sr.", "staff", "principal", "lead", "architect", "iv", "iii")
MODERN_STACK = ("python", "node.js", "nodejs", "node js", "typescript", "golang", "go ", "rust")

# Reparto de los 100 puntos internos antes de convertir a nota 1-10.
WEIGHT_STACK = 45
WEIGHT_SALARY = 25
WEIGHT_WORK_MODE = 20
WEIGHT_SENIORITY = 10

# Peso acumulado de keywords a partir del cual el bloque de stack va lleno.
STACK_SATURATION = 40


@lru_cache(maxsize=512)
def _pattern(term: str) -> re.Pattern[str]:
    """Regex con limites de palabra tolerante a '.net', 'node.js', 'c#'."""
    escaped = re.escape(term.lower())
    prefix = "" if not term[0].isalnum() else r"(?<![a-z0-9+#])"
    suffix = "" if not term[-1].isalnum() else r"(?![a-z0-9#])"
    return re.compile(prefix + escaped + suffix)


def contains_term(text: str, term: str) -> bool:
    return bool(_pattern(term).search(text))


def matched_terms(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if contains_term(text, term)]


def _blockers(offer: JobOffer, criteria: Criteria, today: date) -> list[str]:
    text = offer.searchable_text
    title = offer.title.lower()
    reasons: list[str] = []

    bad_titles = matched_terms(title, criteria.exclude.titles)
    if bad_titles:
        reasons.append(f"titulo excluido: {', '.join(bad_titles)}")

    # El titulo manda. Una descripcion larga menciona medio ecosistema y
    # cualquier oferta acaba pareciendo del perfil; el titulo, no.
    off_profile = matched_terms(title, criteria.exclude.off_profile_titles)
    if off_profile and not matched_terms(title, criteria.exclude.core_title_terms):
        reasons.append(f"titulo de otro perfil: {', '.join(off_profile)}")

    bad_text = [phrase for phrase in criteria.exclude.description if phrase.lower() in text]
    if bad_text:
        reasons.append(f"texto excluido: {', '.join(bad_text)}")

    if offer.work_mode in criteria.work_mode.rejected:
        reasons.append(f"modalidad {offer.work_mode.value}")

    if not matched_terms(text, criteria.keywords.required_any):
        reasons.append("no menciona ninguna tecnologia del perfil")

    veto = matched_terms(text, criteria.exclude.soft_veto_stack)
    if veto and not any(contains_term(text, stack) for stack in MODERN_STACK):
        reasons.append(f"stack vetado sin backend moderno: {', '.join(veto)}")

    if offer.salary.is_known:
        ceiling = offer.salary.best_case
        if ceiling is not None and ceiling < criteria.salary.minimum:
            reasons.append(f"salario {offer.salary.format()} por debajo del minimo")
    elif not criteria.salary.accept_unknown:
        reasons.append("salario no publicado")

    exenta = offer.source in criteria.search.age_exempt_sources
    if offer.posted_at is not None and not exenta:
        age = (today - offer.posted_at).days
        if age > criteria.search.max_age_days:
            reasons.append(f"publicada hace {age} dias")

    return reasons


def _stack_points(offer: JobOffer, criteria: Criteria) -> tuple[int, list[str]]:
    text = offer.searchable_text
    hits = {
        term: weight
        for term, weight in criteria.keywords.weighted.items()
        if contains_term(text, term)
    }
    if not hits:
        return 0, []

    accumulated = min(sum(hits.values()), STACK_SATURATION)
    points = round(WEIGHT_STACK * accumulated / STACK_SATURATION)
    top = sorted(hits, key=lambda term: hits[term], reverse=True)[:6]
    return points, top


def _salary_points(offer: JobOffer, criteria: Criteria) -> tuple[int, str]:
    if not offer.salary.is_known:
        return round(WEIGHT_SALARY * 0.4), "salario no publicado"

    ceiling = offer.salary.best_case or 0
    if ceiling >= criteria.salary.target:
        return WEIGHT_SALARY, f"salario {offer.salary.format()} (por encima del objetivo)"
    return round(WEIGHT_SALARY * 0.7), f"salario {offer.salary.format()} (sobre el minimo)"


def _work_mode_points(offer: JobOffer) -> tuple[int, str]:
    if offer.work_mode is WorkMode.REMOTE:
        return WEIGHT_WORK_MODE, "100% remoto"
    if offer.work_mode is WorkMode.HYBRID:
        return round(WEIGHT_WORK_MODE * 0.6), "hibrido"
    return round(WEIGHT_WORK_MODE * 0.4), "modalidad sin especificar"


def _seniority_points(offer: JobOffer) -> tuple[int, str]:
    title = offer.title.lower()
    if any(contains_term(title, marker) for marker in SENIOR_MARKERS):
        return WEIGHT_SENIORITY, "puesto senior"
    return round(WEIGHT_SENIORITY * 0.5), "seniority sin especificar"


def _competition_points(offer: JobOffer, criteria: Criteria) -> tuple[int, str]:
    """Premia llegar pronto y castiga la cola.

    Va como modificador y no como bloque propio para no descuadrar el reparto
    de los otros cuatro: la competencia no cambia si la oferta encaja contigo,
    cambia tus opciones de que alguien la lea.
    """
    if offer.applicants is None:
        return 0, ""

    ajustes = criteria.scoring.competition
    if offer.applicants <= ajustes.few_applicants:
        return ajustes.bonus, f"solo {offer.applicants} solicitudes, llegas pronto"
    if offer.applicants >= ajustes.many_applicants:
        return -ajustes.penalty, f"{offer.applicants}+ solicitudes, mucha cola"
    return 0, f"{offer.applicants} solicitudes"


def to_ten(points: int) -> int:
    """Convierte los 100 puntos internos en la nota 1-10 que ves en Telegram."""
    return max(1, min(10, round(points / 10)))


def score_offer(offer: JobOffer, criteria: Criteria, today: date | None = None) -> MatchScore:
    today = today or date.today()

    blockers = _blockers(offer, criteria, today)
    if blockers:
        return MatchScore(value=1, blockers=tuple(blockers))

    stack_points, stack_terms = _stack_points(offer, criteria)
    salary_points, salary_reason = _salary_points(offer, criteria)
    mode_points, mode_reason = _work_mode_points(offer)
    seniority_points, seniority_reason = _seniority_points(offer)
    competition_points, competition_reason = _competition_points(offer, criteria)

    total = stack_points + salary_points + mode_points + seniority_points + competition_points
    reasons = [
        f"stack coincidente: {', '.join(stack_terms)}" if stack_terms else "stack generico",
        salary_reason,
        mode_reason,
        seniority_reason,
    ]
    if competition_reason:
        reasons.append(competition_reason)
    return MatchScore(value=to_ten(total), reasons=tuple(reasons))


def is_fresh(offer: JobOffer, criteria: Criteria, today: date | None = None) -> bool:
    """Atajo para filtrar por antiguedad sin puntuar la oferta entera."""
    if offer.posted_at is None:
        return True
    cutoff = (today or date.today()) - timedelta(days=criteria.search.max_age_days)
    return offer.posted_at >= cutoff
