"""Domain models for public-sector postings (oposiciones). No infrastructure
dependencies, same rule as models.py.

Kept separate from JobOffer on purpose: a government vacancy and a private
job posting share almost nothing (no salary, no work mode, no company) and
forcing them into one dataclass would mean a pile of nullable fields nobody
reads at once. They meet later, at the notification layer, as two things
that can both end up in your Telegram.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class Grupo(StrEnum):
    """Spanish civil service pay/qualification groups."""

    A1 = "A1"  # Degree required
    A2 = "A2"  # Degree required
    C1 = "C1"  # Bachillerato / Grado Superior - no degree required
    C2 = "C2"  # ESO / Grado Medio - no degree required
    DESCONOCIDO = "desconocido"

    @property
    def requiere_grado(self) -> bool:
        return self in (Grupo.A1, Grupo.A2)


class Ambito(StrEnum):
    ESTADO = "estado"
    AUTONOMICO = "autonomico"
    LOCAL = "local"
    UNIVERSIDAD = "universidad"
    DESCONOCIDO = "desconocido"


class Turno(StrEnum):
    LIBRE = "libre"
    PROMOCION_INTERNA = "promocion_interna"
    DESCONOCIDO = "desconocido"


class TipoPlaza(StrEnum):
    FIJA = "fija"
    BOLSA = "bolsa"
    INTERINO = "interino"
    DESCONOCIDO = "desconocido"


@dataclass(frozen=True, slots=True)
class Oposicion:
    """A public-sector vacancy or call for applications, as a source returns
    it, already normalised."""

    fuente: str
    identificador: str  # the source's own id (BOE-A-2026-20760, etc.)
    titulo: str
    organismo: str
    url: str
    fecha_publicacion: date
    ambito: Ambito = Ambito.DESCONOCIDO
    grupo: Grupo = Grupo.DESCONOCIDO
    turno: Turno = Turno.DESCONOCIDO
    tipo_plaza: TipoPlaza = TipoPlaza.DESCONOCIDO
    ubicacion: str = ""
    plazo_dias_habiles: int | None = None
    fecha_limite_aproximada: date | None = None
    cuerpo: str = ""  # e.g. "TAI", "Gestion de Sistemas", for Estado TIC bodies
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def elegible(self) -> bool:
        """False for free-access (turno libre) A1/A2 vacancies: those require
        a university degree, which you do not have. Shown anyway, never
        hidden - you decide what to do with that information."""
        return not (self.grupo.requiere_grado and self.turno == Turno.LIBRE)

    @property
    def plazo_abierto(self) -> bool:
        if self.fecha_limite_aproximada is None:
            return True  # unknown deadline: do not silently drop it
        return date.today() <= self.fecha_limite_aproximada

    @property
    def searchable_text(self) -> str:
        parts = [self.titulo, self.organismo, self.cuerpo, self.ubicacion, *self.tags]
        return " ".join(parts).lower()


@dataclass(frozen=True, slots=True)
class PublicMatchScore:
    """The result of scoring an oposicion against your priorities."""

    value: int  # 0-100
    reasons: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    urgent: bool = False

    @property
    def is_rejected(self) -> bool:
        return bool(self.blockers)


@dataclass(frozen=True, slots=True)
class ScoredOposicion:
    oposicion: Oposicion
    score: PublicMatchScore
    fingerprint: str
    summary: str = ""
