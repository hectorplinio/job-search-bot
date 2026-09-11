from __future__ import annotations

from datetime import date

import pytest

from jobbot.domain.criteria import Criteria
from jobbot.domain.models import JobOffer, SalaryRange, WorkMode
from jobbot.domain.profile import CandidateProfile
from jobbot.settings import PROJECT_ROOT


@pytest.fixture
def criteria() -> Criteria:
    """Los criterios reales del proyecto, no unos de mentira: si alguien rompe
    config.yaml, los tests lo cantan."""
    return Criteria.load(PROJECT_ROOT / "config.yaml")


@pytest.fixture
def profile() -> CandidateProfile:
    return CandidateProfile.load(PROJECT_ROOT / "profile" / "cv.yaml")


def make_offer(**overrides) -> JobOffer:
    defaults = dict(
        source="test",
        external_id="test:1",
        title="Senior Backend Engineer (Python)",
        company="Acme",
        url="https://example.com/jobs/1",
        description=(
            "Buscamos un backend senior con Python, FastAPI, PostgreSQL y AWS. "
            "Trabajamos con microservices, Kubernetes y TDD. Salario 55.000€ - 65.000€."
        ),
        location="Madrid",
        work_mode=WorkMode.REMOTE,
        salary=SalaryRange(55_000, 65_000),
        posted_at=date.today(),
    )
    defaults.update(overrides)
    return JobOffer(**defaults)


@pytest.fixture
def offer() -> JobOffer:
    return make_offer()


class FakeHttp:
    """HttpClient de mentira: devuelve fixtures segun la URL pedida."""

    def __init__(self, text_by_fragment: dict[str, str] | None = None, json_payload=None) -> None:
        self.text_by_fragment = text_by_fragment or {}
        self.json_payload = json_payload
        self.calls: list[str] = []

    async def get_text(self, url: str, **_kwargs) -> str:
        self.calls.append(url)
        for fragment, body in self.text_by_fragment.items():
            if fragment in url:
                return body
        raise RuntimeError(f"FakeHttp no tiene fixture para {url}")

    async def get_json(self, url: str, **_kwargs):
        self.calls.append(url)
        if self.json_payload is None:
            raise RuntimeError(f"FakeHttp no tiene JSON para {url}")
        return self.json_payload
