"""The oposiciones history, in SQLite. Same file, same database as the
private offers (one `.db_path`), but its own table: the shapes do not
overlap enough to share one (no salary, no work mode - instead grupo, plazo,
organismo), so forcing them together would mean a schema full of columns
that only ever apply to one side.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from ..domain.public_models import (
    Ambito,
    Grupo,
    Oposicion,
    PublicMatchScore,
    ScoredOposicion,
    TipoPlaza,
    Turno,
)

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS oposiciones (
    fingerprint              TEXT PRIMARY KEY,
    fuente                   TEXT NOT NULL,
    identificador             TEXT NOT NULL,
    titulo                   TEXT NOT NULL,
    organismo                 TEXT NOT NULL,
    url                      TEXT NOT NULL,
    fecha_publicacion         TEXT NOT NULL,
    ambito                   TEXT NOT NULL DEFAULT 'desconocido',
    grupo                    TEXT NOT NULL DEFAULT 'desconocido',
    turno                    TEXT NOT NULL DEFAULT 'desconocido',
    tipo_plaza                TEXT NOT NULL DEFAULT 'desconocido',
    ubicacion                 TEXT NOT NULL DEFAULT '',
    plazo_dias_habiles          INTEGER,
    fecha_limite_aproximada     TEXT,
    cuerpo                   TEXT NOT NULL DEFAULT '',
    score                    INTEGER NOT NULL DEFAULT 0,
    reasons                  TEXT NOT NULL DEFAULT '[]',
    blockers                 TEXT NOT NULL DEFAULT '[]',
    urgent                   INTEGER NOT NULL DEFAULT 0,
    summary                  TEXT NOT NULL DEFAULT '',
    notified                 INTEGER NOT NULL DEFAULT 0,
    first_seen                TEXT NOT NULL,
    last_seen                 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_oposiciones_notified ON oposiciones(notified, score DESC);
CREATE INDEX IF NOT EXISTS idx_oposiciones_fuente ON oposiciones(fuente);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class SqliteOposicionRepository:
    """PublicOfferRepository implemented on a SQLite file."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.db_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SqliteOposicionRepository:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def is_known(self, fingerprint: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM oposiciones WHERE fingerprint = ? LIMIT 1", (fingerprint,)
        ).fetchone()
        return row is not None

    def remember(self, scored: ScoredOposicion, *, notified: bool) -> None:
        op = scored.oposicion
        now = _now()
        self._connection.execute(
            """
            INSERT INTO oposiciones (
                fingerprint, fuente, identificador, titulo, organismo, url,
                fecha_publicacion, ambito, grupo, turno, tipo_plaza, ubicacion,
                plazo_dias_habiles, fecha_limite_aproximada, cuerpo,
                score, reasons, blockers, urgent, summary, notified,
                first_seen, last_seen
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(fingerprint) DO UPDATE SET
                last_seen = excluded.last_seen,
                score     = excluded.score,
                summary   = excluded.summary,
                notified  = oposiciones.notified OR excluded.notified
            """,
            (
                scored.fingerprint,
                op.fuente,
                op.identificador,
                op.titulo,
                op.organismo,
                op.url,
                op.fecha_publicacion.isoformat(),
                op.ambito.value,
                op.grupo.value,
                op.turno.value,
                op.tipo_plaza.value,
                op.ubicacion,
                op.plazo_dias_habiles,
                op.fecha_limite_aproximada.isoformat() if op.fecha_limite_aproximada else None,
                op.cuerpo,
                scored.score.value,
                json.dumps(list(scored.score.reasons), ensure_ascii=False),
                json.dumps(list(scored.score.blockers), ensure_ascii=False),
                int(scored.score.urgent),
                scored.summary,
                int(notified),
                now,
                now,
            ),
        )
        self._connection.commit()

    def mark_notified(self, fingerprint: str) -> None:
        self._connection.execute(
            "UPDATE oposiciones SET notified = 1, last_seen = ? WHERE fingerprint = ?",
            (_now(), fingerprint),
        )
        self._connection.commit()

    def top_pending(self, limit: int = 10, min_score: int = 0) -> list[ScoredOposicion]:
        """Urgent ones first, regardless of score - then by score."""
        rows = self._connection.execute(
            """
            SELECT * FROM oposiciones
            WHERE notified = 0 AND blockers = '[]' AND (score >= ? OR urgent = 1)
            ORDER BY urgent DESC, score DESC, last_seen DESC
            LIMIT ?
            """,
            (min_score, limit),
        ).fetchall()
        return [self._to_scored(row) for row in rows]

    @staticmethod
    def _to_scored(row: sqlite3.Row) -> ScoredOposicion:
        oposicion = Oposicion(
            fuente=row["fuente"],
            identificador=row["identificador"],
            titulo=row["titulo"],
            organismo=row["organismo"],
            url=row["url"],
            fecha_publicacion=date.fromisoformat(row["fecha_publicacion"]),
            ambito=Ambito(row["ambito"]),
            grupo=Grupo(row["grupo"]),
            turno=Turno(row["turno"]),
            tipo_plaza=TipoPlaza(row["tipo_plaza"]),
            ubicacion=row["ubicacion"],
            plazo_dias_habiles=row["plazo_dias_habiles"],
            fecha_limite_aproximada=(
                date.fromisoformat(row["fecha_limite_aproximada"])
                if row["fecha_limite_aproximada"]
                else None
            ),
            cuerpo=row["cuerpo"],
        )
        score = PublicMatchScore(
            value=row["score"],
            reasons=tuple(json.loads(row["reasons"])),
            blockers=tuple(json.loads(row["blockers"])),
            urgent=bool(row["urgent"]),
        )
        return ScoredOposicion(
            oposicion=oposicion, score=score, fingerprint=row["fingerprint"], summary=row["summary"]
        )
