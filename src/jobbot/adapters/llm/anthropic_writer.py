"""The Claude adapter: a second opinion on scoring, and writing materials.

It uses structured outputs (`messages.parse`) to avoid parsing free text: if
the model strays from the schema the SDK rejects it, and we fall back to the
rule-based score, which always exists.
"""

from __future__ import annotations

import asyncio
import logging

import anthropic
from pydantic import BaseModel, Field

from ...domain.cost import TokenUsage
from ...domain.models import ApplicationDocuments, JobOffer, MatchScore
from ...domain.profile import CandidateProfile
from .prompts import rating_prompt, rating_system, writing_prompt, writing_system

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5"
# How many postings go into a single scoring call. Bigger is cheaper, but the
# model starts mixing them up with one another.
RATING_BATCH_SIZE = 6


class OfferVerdict(BaseModel):
    offer_index: int = Field(description="Indice de la oferta dentro del lote, empezando en 0")
    score: int = Field(ge=1, le=10)
    fit_summary: str = Field(description="Por que encaja, en espanol, maximo 25 palabras")
    matching_points: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)


class RatingBatch(BaseModel):
    verdicts: list[OfferVerdict]


class DocumentsOutput(BaseModel):
    cover_letter: str
    cv_summary: str
    highlighted_experience: list[str] = Field(default_factory=list)
    detected_stack: list[str] = Field(default_factory=list)


class AnthropicWriter:
    """DocumentWriter implemented against the Messages API."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 8000,
        usage_log=None,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self._usage_log = usage_log

    def _record(self, response, operation: str) -> None:
        """Records the spend. It must never sink a call that already worked."""
        if self._usage_log is None:
            return
        try:
            uso = response.usage
            self._usage_log.record(
                TokenUsage(
                    model=self._model,
                    input_tokens=getattr(uso, "input_tokens", 0) or 0,
                    output_tokens=getattr(uso, "output_tokens", 0) or 0,
                    cache_read_tokens=getattr(uso, "cache_read_input_tokens", 0) or 0,
                    cache_write_tokens=getattr(uso, "cache_creation_input_tokens", 0) or 0,
                ),
                operation,
            )
        except Exception:  # noqa: BLE001 - bookkeeping, not the task itself
            logger.warning("No pude apuntar el gasto de la llamada", exc_info=True)

    async def rate(
        self,
        candidates: list[tuple[JobOffer, MatchScore]],
        profile: CandidateProfile,
        *,
        salary_minimum: int,
        salary_target: int,
    ) -> list[tuple[MatchScore, str]]:
        """Re-scores a batch of postings.

        Returns, in the same order, the final score and the fit summary. If a
        call fails, those postings keep their rule-based score.
        """
        if not candidates:
            return []

        batches = [
            candidates[start : start + RATING_BATCH_SIZE]
            for start in range(0, len(candidates), RATING_BATCH_SIZE)
        ]
        results = await asyncio.gather(
            *(self._rate_batch(batch, profile, salary_minimum, salary_target) for batch in batches)
        )
        return [item for batch_result in results for item in batch_result]

    async def _rate_batch(
        self,
        batch: list[tuple[JobOffer, MatchScore]],
        profile: CandidateProfile,
        salary_minimum: int,
        salary_target: int,
    ) -> list[tuple[MatchScore, str]]:
        fallback = [(rule_score, "") for _offer, rule_score in batch]
        try:
            response = await self._client.messages.parse(
                model=self._model,
                max_tokens=self._max_tokens,
                system=rating_system(profile),
                messages=[
                    {
                        "role": "user",
                        "content": rating_prompt(batch, profile, salary_minimum, salary_target),
                    }
                ],
                output_format=RatingBatch,
            )
        except anthropic.APIError:
            logger.exception("Claude fallo puntuando un lote; se usan las notas por reglas")
            return fallback

        self._record(response, "puntuar ofertas")
        parsed = response.parsed_output
        if parsed is None:
            return fallback

        by_index = {verdict.offer_index: verdict for verdict in parsed.verdicts}
        results: list[tuple[MatchScore, str]] = []
        for index, (_offer, rule_score) in enumerate(batch):
            verdict = by_index.get(index)
            if verdict is None:
                results.append((rule_score, ""))
                continue
            results.append(
                (
                    MatchScore(
                        value=verdict.score,
                        reasons=tuple(verdict.matching_points) or rule_score.reasons,
                        blockers=tuple(verdict.concerns[:2]) if verdict.score <= 2 else (),
                        source_of_truth="llm",
                    ),
                    verdict.fit_summary,
                )
            )
        return results

    async def write(self, offer: JobOffer, profile: CandidateProfile) -> ApplicationDocuments:
        response = await self._client.messages.parse(
            model=self._model,
            max_tokens=self._max_tokens,
            system=writing_system(profile),
            messages=[{"role": "user", "content": writing_prompt(offer, profile)}],
            output_format=DocumentsOutput,
        )
        self._record(response, "escribir candidatura")
        parsed = response.parsed_output
        if parsed is None:
            raise RuntimeError("Claude no devolvio documentos validos para esta oferta")

        return ApplicationDocuments(
            cover_letter=parsed.cover_letter.strip(),
            cv_summary=parsed.cv_summary.strip(),
            highlighted_experience=tuple(parsed.highlighted_experience),
            detected_stack=tuple(parsed.detected_stack),
        )
