"""The candidate profile, loaded from profile/cv.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class Experience(BaseModel):
    id: str
    company: str
    role: str
    location: str | None = None
    start: str | None = None
    end: str | None = None
    stack: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)

    @property
    def period(self) -> str:
        return f"{self.start or '?'} - {self.end or 'actualidad'}"


class AnchorRule(BaseModel):
    """If the posting mentions one of these words, lean the letter on that
    experience."""

    keywords: list[str] = Field(default_factory=list)
    experience: str


class CoverLetterAnchors(BaseModel):
    """Which experience to highlight in the cover letter. The values are ids
    from `experience`, so every profile brings its own and the prompt knows
    nothing about any particular company."""

    always: str | None = None
    when: list[AnchorRule] = Field(default_factory=list)


class CandidateProfile(BaseModel):
    name: str
    headline: str = ""
    email: str = ""
    location: str = ""
    open_to: str = ""
    languages: list[str] = Field(default_factory=list)
    summary: str = ""
    skills: dict[str, list[str]] = Field(default_factory=dict)
    experience: list[Experience] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    emphasis_rules: dict[str, list[str]] = Field(default_factory=dict)
    cover_letter_anchors: CoverLetterAnchors = Field(default_factory=CoverLetterAnchors)

    @classmethod
    def load(cls, path: str | Path) -> CandidateProfile:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls.model_validate(raw)

    def by_id(self, experience_id: str) -> Experience | None:
        return next((item for item in self.experience if item.id == experience_id), None)

    def all_skills(self) -> list[str]:
        return [skill for group in self.skills.values() for skill in group]

    def emphasis_for(self, offer_text: str) -> list[Experience]:
        """The experiences to highlight, based on what the posting mentions.

        Returns the most referenced ones, without repeats, and falls back to
        chronological order when the posting triggers no rule at all.
        """
        lowered = offer_text.lower()
        votes: dict[str, int] = {}
        for keyword, experience_ids in self.emphasis_rules.items():
            if keyword.lower() in lowered:
                for experience_id in experience_ids:
                    votes[experience_id] = votes.get(experience_id, 0) + 1

        ranked = sorted(votes, key=lambda key: votes[key], reverse=True)
        chosen = [item for item in (self.by_id(key) for key in ranked) if item is not None]
        for experience in self.experience:
            if experience not in chosen:
                chosen.append(experience)
        return chosen

    def as_context(self) -> str:
        """A plain-text view of the profile, to drop into the prompt."""
        lines = [
            f"Name: {self.name}",
            f"Headline: {self.headline}",
            f"Location: {self.location} | Open to: {self.open_to}",
            f"Languages: {', '.join(self.languages)}",
            "",
            "CURRENT CV SUMMARY:",
            self.summary.strip(),
            "",
            "SKILLS:",
        ]
        for group, skills in self.skills.items():
            lines.append(f"- {group}: {', '.join(skills)}")
        lines.append("")
        lines.append("EXPERIENCE:")
        for experience in self.experience:
            lines.append(
                f"[{experience.id}] {experience.role} at {experience.company} "
                f"({experience.period}) - stack: {', '.join(experience.stack)}"
            )
            lines.extend(f"  * {highlight.strip()}" for highlight in experience.highlights)
        if self.education:
            lines.append("")
            lines.append("EDUCATION:")
            lines.extend(f"- {item}" for item in self.education)
        return "\n".join(lines)
