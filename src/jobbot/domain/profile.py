"""Perfil del candidato, cargado desde profile/cv.yaml."""

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


class CoverLetterAnchors(BaseModel):
    always: str | None = None
    ai_or_llm: str | None = None
    node_or_typescript: str | None = None


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
        """Experiencias a destacar segun lo que menciona la oferta.

        Devuelve las que mas veces aparecen referenciadas, sin repetir, y
        completa con el orden cronologico si la oferta no dispara ninguna regla.
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
        """Version en texto plano del perfil, para meterla en el prompt."""
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
