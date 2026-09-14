"""Historial de ofertas en SQLite.

Guarda todo lo que el bot ha visto, no solo lo que te ha mandado. Asi la
deduplicacion sobrevive a los reinicios y puedes revisar despues por que una
oferta se descarto.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from ..domain.models import JobOffer, MatchScore, SalaryRange, ScoredOffer, WorkMode

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
    fingerprint   TEXT PRIMARY KEY,
    url_key       TEXT NOT NULL,
    source        TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    title         TEXT NOT NULL,
    company       TEXT NOT NULL,
    url           TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    location      TEXT,
    work_mode     TEXT NOT NULL DEFAULT 'unknown',
    salary_min    INTEGER,
    salary_max    INTEGER,
    currency      TEXT NOT NULL DEFAULT 'EUR',
    posted_at     TEXT,
    score         INTEGER NOT NULL DEFAULT 0,
    reasons       TEXT NOT NULL DEFAULT '[]',
    blockers      TEXT NOT NULL DEFAULT '[]',
    summary       TEXT NOT NULL DEFAULT '',
    notified      INTEGER NOT NULL DEFAULT 0,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_offers_url_key ON offers(url_key);
CREATE INDEX IF NOT EXISTS idx_offers_notified ON offers(notified, score DESC);
CREATE INDEX IF NOT EXISTS idx_offers_source ON offers(source);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class SqliteOfferRepository:
    """Implementacion de OfferRepository sobre un fichero SQLite."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.db_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SqliteOfferRepository:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def is_known(self, fingerprint: str, url_key: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM offers WHERE fingerprint = ? OR url_key = ? LIMIT 1",
            (fingerprint, url_key),
        ).fetchone()
        return row is not None

    def remember(self, scored: ScoredOffer, *, notified: bool, url_key: str = "") -> None:
        offer = scored.offer
        now = _now()
        self._connection.execute(
            """
            INSERT INTO offers (
                fingerprint, url_key, source, external_id, title, company, url,
                description, location, work_mode, salary_min, salary_max, currency,
                posted_at, score, reasons, blockers, summary, notified,
                first_seen, last_seen
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(fingerprint) DO UPDATE SET
                last_seen = excluded.last_seen,
                score     = excluded.score,
                summary   = excluded.summary,
                notified  = offers.notified OR excluded.notified
            """,
            (
                scored.fingerprint,
                url_key or scored.fingerprint,
                offer.source,
                offer.external_id,
                offer.title,
                offer.company,
                offer.url,
                offer.description[:20000],
                offer.location,
                offer.work_mode.value,
                offer.salary.minimum,
                offer.salary.maximum,
                offer.salary.currency,
                offer.posted_at.isoformat() if offer.posted_at else None,
                scored.score.value,
                json.dumps(list(scored.score.reasons), ensure_ascii=False),
                json.dumps(list(scored.score.blockers), ensure_ascii=False),
                scored.summary,
                int(notified),
                now,
                now,
            ),
        )
        self._connection.commit()

    def mark_notified(self, fingerprint: str) -> None:
        self._connection.execute(
            "UPDATE offers SET notified = 1, last_seen = ? WHERE fingerprint = ?",
            (_now(), fingerprint),
        )
        self._connection.commit()

    def top_pending(self, limit: int = 10, min_score: int = 0) -> list[ScoredOffer]:
        """Lo mejor que esta guardado y aun no te ha llegado.

        Incluye lo de ejecuciones anteriores que se quedo fuera por el tope
        de mensajes, no solo lo de la pasada actual.
        """
        rows = self._connection.execute(
            """
            SELECT * FROM offers
            WHERE notified = 0 AND blockers = '[]' AND score >= ?
            ORDER BY score DESC, last_seen DESC
            LIMIT ?
            """,
            (min_score, limit),
        ).fetchall()
        return [self._to_scored(row) for row in rows]

    def count_pending(self, min_score: int = 0) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS c FROM offers "
            "WHERE notified = 0 AND blockers = '[]' AND score >= ?",
            (min_score,),
        ).fetchone()
        return int(row["c"])

    def recent(self, limit: int = 10) -> list[ScoredOffer]:
        rows = self._connection.execute(
            "SELECT * FROM offers WHERE notified = 1 ORDER BY last_seen DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._to_scored(row) for row in rows]

    def find_by_fingerprint_prefix(self, prefix: str) -> ScoredOffer | None:
        """Los botones de Telegram solo pueden llevar 64 bytes, asi que
        mandan la huella recortada."""
        row = self._connection.execute(
            "SELECT * FROM offers WHERE fingerprint LIKE ? LIMIT 1", (f"{prefix}%",)
        ).fetchone()
        return self._to_scored(row) if row else None

    def find_by_url(self, url: str) -> ScoredOffer | None:
        row = self._connection.execute(
            "SELECT * FROM offers WHERE url = ? LIMIT 1", (url,)
        ).fetchone()
        return self._to_scored(row) if row else None

    def stats(self) -> dict[str, int]:
        totals = self._connection.execute("""
            SELECT
                COUNT(*)                                   AS vistas,
                SUM(CASE WHEN notified = 1 THEN 1 ELSE 0 END) AS enviadas,
                SUM(CASE WHEN blockers != '[]' THEN 1 ELSE 0 END) AS descartadas,
                COALESCE(MAX(score), 0)                    AS mejor_nota
            FROM offers
            """).fetchone()
        # sqlite3.Row itera valores, no claves: .keys() no es redundante aqui.
        result = {key: int(totals[key] or 0) for key in totals.keys()}  # noqa: SIM118

        by_source = self._connection.execute(
            "SELECT source, COUNT(*) AS total FROM offers GROUP BY source ORDER BY total DESC"
        ).fetchall()
        for row in by_source:
            result[f"fuente:{row['source']}"] = int(row["total"])
        return result

    @staticmethod
    def _to_scored(row: sqlite3.Row) -> ScoredOffer:
        posted_at = date.fromisoformat(row["posted_at"]) if row["posted_at"] else None
        offer = JobOffer(
            source=row["source"],
            external_id=row["external_id"],
            title=row["title"],
            company=row["company"],
            url=row["url"],
            description=row["description"],
            location=row["location"],
            work_mode=WorkMode(row["work_mode"]),
            salary=SalaryRange(
                minimum=row["salary_min"],
                maximum=row["salary_max"],
                currency=row["currency"],
            ),
            posted_at=posted_at,
        )
        score = MatchScore(
            value=row["score"],
            reasons=tuple(json.loads(row["reasons"])),
            blockers=tuple(json.loads(row["blockers"])),
        )
        return ScoredOffer(
            offer=offer,
            score=score,
            fingerprint=row["fingerprint"],
            summary=row["summary"],
        )
