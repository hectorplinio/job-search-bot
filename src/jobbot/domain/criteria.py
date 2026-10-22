"""Search criteria, loaded from config.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .models import WorkMode


class SearchCriteria(BaseModel):
    queries: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=lambda: ["Spain"])
    max_results_per_query: int = 25
    max_results_per_source: int = 40
    max_age_days: int = 21
    # A separate window for sources where age means something else. On a
    # company's own board a two-month-old posting is still open, because filled
    # ones are taken down. But with no cap, year-old ghost reqs slip through.
    max_age_days_by_source: dict[str, int] = Field(default_factory=lambda: {"companies": 90})

    def age_limit_for(self, source: str) -> int:
        return self.max_age_days_by_source.get(source, self.max_age_days)


class SalaryCriteria(BaseModel):
    currency: str = "EUR"
    minimum: int = 40_000
    target: int = 50_000
    accept_unknown: bool = True


class WorkModeCriteria(BaseModel):
    accepted: list[WorkMode] = Field(
        default_factory=lambda: [WorkMode.REMOTE, WorkMode.HYBRID, WorkMode.UNKNOWN]
    )
    rejected: list[WorkMode] = Field(default_factory=lambda: [WorkMode.ONSITE])


class KeywordCriteria(BaseModel):
    required_any: list[str] = Field(default_factory=list)
    weighted: dict[str, int] = Field(default_factory=dict)


class ExclusionCriteria(BaseModel):
    titles: list[str] = Field(default_factory=list)
    description: list[str] = Field(default_factory=list)
    off_profile_titles: list[str] = Field(default_factory=list)
    core_title_terms: list[str] = Field(default_factory=list)
    soft_veto_stack: list[str] = Field(default_factory=list)
    # Drops postings with too long a queue. Only LinkedIn publishes the
    # number, so null (no filter) is the sensible default: otherwise the
    # sources that do not report it would be penalised for no reason.
    max_applicants: int | None = None


class CompetitionCriteria(BaseModel):
    """How many people have already applied. LinkedIn shows it on the posting."""

    few_applicants: int = 25
    many_applicants: int = 150
    bonus: int = 8
    penalty: int = 8


class ScoringCriteria(BaseModel):
    notify_threshold: int = 6
    use_llm: bool = True
    llm_min_rule_score: int = 5
    llm_max_offers_per_run: int = 40
    competition: CompetitionCriteria = Field(default_factory=CompetitionCriteria)


class ScheduleCriteria(BaseModel):
    enabled: bool = True
    every_hours: float = 4
    first_run_after_minutes: float = 3


class TelegramCriteria(BaseModel):
    max_alerts_per_run: int = 50
    delay_between_messages: float = 1.2


class PublicCriteria(BaseModel):
    """Criteria for the public-sector line (oposiciones y bolsas)."""

    enabled: bool = True
    # Matched against title + epigraph, accents and case stripped.
    keywords: list[str] = Field(
        default_factory=lambda: [
            "informatica",
            "sistemas de informacion",
            "tecnologias de la informacion",
            "tic",
            "soporte tecnico",
            "programador",
            "desarrollador",
            "analista",
        ]
    )
    # Priority geographic scope: always notified, regardless of score.
    priority_locations: list[str] = Field(
        default_factory=lambda: [
            "alicante",
            "diputacion de alicante",
            "generalitat valenciana",
            "universidad de alicante",
            "universitat d'alacant",
            "umh",
        ]
    )
    # From the Estado, only these TIC bodies are worth matching - a generic
    # "informatica" hit elsewhere in a huge Estado-wide call is mostly noise.
    estado_cuerpos_tic: list[str] = Field(
        default_factory=lambda: [
            "tecnico auxiliar de informatica",
            "tai",
            "cuerpo de gestion de sistemas",
            "gestion de sistemas e informatica",
            "cuerpo superior de sistemas",
            "superior de sistemas y tecnologia",
        ]
    )
    # Default when the announcement's own text does not state a deadline.
    default_plazo_dias_habiles: int = 20
    # Minimum score (0-100) to notify a non-urgent oposicion. Urgent ones
    # (open deadline, priority scope, eligible) bypass this entirely.
    notify_threshold: int = 50
    # Separate cadence from the private line: BOE publishes once a day on
    # working days, so checking every 4h like the private search would be
    # nine wasted requests for one useful one. Twice a day is plenty.
    schedule_every_hours: float = 12
    first_run_after_minutes: float = 5


class EmailCriteria(BaseModel):
    """Criteria for the reply-tracking line (Gmail)."""

    enabled: bool = False
    # Regular runs only need a short lookback - the search is incremental,
    # already-seen messages are filtered out by message_id regardless. A
    # longer window is for the one-off backfill (`jobbot check-mail --days 60`).
    days_back: int = 3
    schedule_every_hours: float = 6
    first_run_after_minutes: float = 7


class Criteria(BaseModel):
    search: SearchCriteria = Field(default_factory=SearchCriteria)
    salary: SalaryCriteria = Field(default_factory=SalaryCriteria)
    work_mode: WorkModeCriteria = Field(default_factory=WorkModeCriteria)
    keywords: KeywordCriteria = Field(default_factory=KeywordCriteria)
    exclude: ExclusionCriteria = Field(default_factory=ExclusionCriteria)
    scoring: ScoringCriteria = Field(default_factory=ScoringCriteria)
    schedule: ScheduleCriteria = Field(default_factory=ScheduleCriteria)
    sources: dict[str, dict] = Field(default_factory=dict)
    telegram: TelegramCriteria = Field(default_factory=TelegramCriteria)
    public: PublicCriteria = Field(default_factory=PublicCriteria)
    email: EmailCriteria = Field(default_factory=EmailCriteria)

    @classmethod
    def load(cls, path: str | Path) -> Criteria:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls.model_validate(raw)

    def source_options(self, name: str) -> dict:
        return self.sources.get(name, {})

    def source_enabled(self, name: str) -> bool:
        return bool(self.source_options(name).get("enabled", False))
