"""Which model each operation uses, and what gets written to the ledger.

Scoring is the bulk of the spend, so it runs on the cheap model; writing the
application keeps the expensive one. These tests exist because that split is
easy to undo by accident with a single `self._model`.
"""

from __future__ import annotations

import pytest

from jobbot.adapters.llm.anthropic_writer import (
    DEFAULT_MODEL,
    RATING_MODEL,
    AnthropicWriter,
    DocumentsOutput,
    OfferVerdict,
    RatingBatch,
)
from jobbot.domain.models import MatchScore

from .conftest import make_offer


class FakeUsage:
    input_tokens = 100
    output_tokens = 20
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class FakeResponse:
    def __init__(self, parsed):
        self.parsed_output = parsed
        self.usage = FakeUsage()


class FakeMessages:
    """Records the model each call asked for, and answers with a fixture."""

    def __init__(self, parsed):
        self.parsed = parsed
        self.models: list[str] = []

    async def parse(self, *, model, **_kwargs):
        self.models.append(model)
        return FakeResponse(self.parsed)


class FakeClient:
    def __init__(self, parsed):
        self.messages = FakeMessages(parsed)


class FakeLog:
    def __init__(self):
        self.entries: list[tuple[str, str]] = []

    def record(self, usage, operation):
        self.entries.append((usage.model, operation))


def writer_with(parsed, log=None) -> tuple[AnthropicWriter, FakeClient]:
    writer = AnthropicWriter("test-key", usage_log=log)
    client = FakeClient(parsed)
    writer._client = client  # the constructor builds the real one
    return writer, client


@pytest.mark.asyncio
async def test_puntuar_usa_el_modelo_barato(profile):
    verdict = OfferVerdict(offer_index=0, score=8, fit_summary="encaja")
    log = FakeLog()
    writer, client = writer_with(RatingBatch(verdicts=[verdict]), log)

    await writer.rate(
        [(make_offer(), MatchScore(value=6))],
        profile,
        salary_minimum=40_000,
        salary_target=50_000,
    )

    assert client.messages.models == [RATING_MODEL]
    assert log.entries == [(RATING_MODEL, "puntuar ofertas")]


@pytest.mark.asyncio
async def test_escribir_usa_el_modelo_bueno(profile, offer):
    documents = DocumentsOutput(cover_letter="Hola", cv_summary="Resumen")
    log = FakeLog()
    writer, client = writer_with(documents, log)

    await writer.write(offer, profile)

    assert client.messages.models == [DEFAULT_MODEL]
    assert log.entries == [(DEFAULT_MODEL, "escribir candidatura")]


def test_los_dos_modelos_son_distintos():
    assert RATING_MODEL != DEFAULT_MODEL
