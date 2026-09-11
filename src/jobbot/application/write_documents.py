"""Caso de uso del modo manual: de un enlace (o un texto pegado) a los
materiales de candidatura."""

from __future__ import annotations

import logging
import re

from ..domain.models import ApplicationDocuments, JobOffer
from ..domain.profile import CandidateProfile

logger = logging.getLogger(__name__)

_URL = re.compile(r"https?://\S+")


def looks_like_url(text: str) -> bool:
    return bool(_URL.match(text.strip()))


def extract_url(text: str) -> str | None:
    match = _URL.search(text or "")
    return match.group(0).rstrip(").,") if match else None


class WriteDocuments:
    """Lee la oferta y le pide a Claude la carta y el summary."""

    def __init__(self, *, reader, writer, profile: CandidateProfile) -> None:
        self._reader = reader
        self._writer = writer
        self._profile = profile

    async def from_input(self, raw: str) -> tuple[JobOffer, ApplicationDocuments]:
        """Acepta tanto una URL como el texto de la oferta pegado a pelo."""
        url = extract_url(raw)
        offer = await self._reader.read(url) if url else self._reader.from_text(raw)
        documents = await self._writer.write(offer, self._profile)
        return offer, documents

    async def from_offer(self, offer: JobOffer) -> ApplicationDocuments:
        return await self._writer.write(offer, self._profile)
