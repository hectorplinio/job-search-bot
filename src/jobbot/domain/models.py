"""Domain models. No infrastructure dependencies."""

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
    """Gross annual salary. `None` means "the posting does not say"."""

    minimum: int | None = None
    maximum: int | None = None
    currency: str = "EUR"

    @property
    def is_known(self) -> bool:
        return self.minimum is not None or self.maximum is not None

    @property
    def best_case(self) -> int | None:
        """The top of the range, or the bottom when there is no top."""
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
    """A job posting as a source returns it, already normalised."""

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
    # How many people have already applied, when the source publishes it.
    # Applying on day one to a posting with 5 applicants is nothing like
    # applying to the same one with 200.
    applicants: int | None = None
    tags: tuple[str, ...] = ()

    @property
    def searchable_text(self) -> str:
        """The whole posting in lowercase, for keyword matching."""
        parts = [self.title, self.company, self.location or "", self.description, *self.tags]
        return " ".join(parts).lower()

    def with_description(self, description: str) -> JobOffer:
        return replace(self, description=description)


@dataclass(frozen=True, slots=True)
class MatchScore:
    """The result of scoring a posting against the profile."""

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
    summary: str = ""  # the "why it fits" line that goes to Telegram


@dataclass(frozen=True, slots=True)
class ApplicationDocuments:
    """What the LLM writes for one specific posting."""

    cover_letter: str
    cv_summary: str
    highlighted_experience: tuple[str, ...] = ()
    detected_stack: tuple[str, ...] = ()
