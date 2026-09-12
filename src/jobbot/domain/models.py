"""Modelos del dominio. Sin dependencias de infraestructura."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from enum import StrEnum


class WorkMode(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SalaryRange:
    """Salario anual bruto. `None` significa "la oferta no lo dice"."""

    minimum: int | None = None
    maximum: int | None = None
    currency: str = "EUR"

    @property
    def is_known(self) -> bool:
        return self.minimum is not None or self.maximum is not None

    @property
    def best_case(self) -> int | None:
        """El techo del rango, o el suelo si no hay techo."""
        return self.maximum if self.maximum is not None else self.minimum

    @property
    def worst_case(self) -> int | None:
        return self.minimum if self.minimum is not None else self.maximum

    def format(self) -> str:
        if not self.is_known:
            return "no publicado"
        symbol = "€" if self.currency == "EUR" else f" {self.currency}"

        def money(value: int) -> str:
            return f"{value:,}".replace(",", ".") + symbol

        if self.minimum is not None and self.maximum is not None:
            if self.minimum == self.maximum:
                return money(self.minimum)
            return f"{money(self.minimum)} - {money(self.maximum)}"
        return money(self.best_case)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class JobOffer:
    """Una oferta tal y como la devuelve una fuente, ya normalizada."""

    source: str
    external_id: str
    title: str
    company: str
    url: str
    description: str = ""
    location: str | None = None
    work_mode: WorkMode = WorkMode.UNKNOWN
    salary: SalaryRange = field(default_factory=SalaryRange)
    posted_at: date | None = None
    # Cuantos han solicitado ya, cuando la fuente lo publica. Aplicar el
    # primer dia a una oferta con 5 candidatos no se parece en nada a
    # aplicar a la misma con 200.
    applicants: int | None = None
    tags: tuple[str, ...] = ()

    @property
    def searchable_text(self) -> str:
        """Todo el texto de la oferta en minusculas, para buscar keywords."""
        parts = [self.title, self.company, self.location or "", self.description, *self.tags]
        return " ".join(parts).lower()

    def with_description(self, description: str) -> JobOffer:
        return replace(self, description=description)


@dataclass(frozen=True, slots=True)
class MatchScore:
    """Resultado de evaluar una oferta contra el perfil."""

    value: int  # 1-10
    reasons: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    source_of_truth: str = "rules"  # "rules" | "llm"

    @property
    def is_rejected(self) -> bool:
        return bool(self.blockers)


@dataclass(frozen=True, slots=True)
class ScoredOffer:
    offer: JobOffer
    score: MatchScore
    fingerprint: str
    summary: str = ""  # el "por que encaja" que va a Telegram


@dataclass(frozen=True, slots=True)
class ApplicationDocuments:
    """Lo que genera el LLM para una oferta concreta."""

    cover_letter: str
    cv_summary: str
    highlighted_experience: tuple[str, ...] = ()
    detected_stack: tuple[str, ...] = ()
