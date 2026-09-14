"""Registro de lo que se gasta en la API de Claude.

Guarda el coste calculado en el momento de la llamada, no solo los tokens.
Si Anthropic cambia precios manana, lo que ya gastaste sigue contando con el
precio que tenia entonces.

Vive en el mismo fichero SQLite que el historial de ofertas: una sola cosa
que respaldar.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ..domain.cost import TokenUsage, cost_usd

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_usage (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    happened_at        TEXT NOT NULL,
    operation          TEXT NOT NULL,
    model              TEXT NOT NULL,
    input_tokens       INTEGER NOT NULL DEFAULT 0,
    output_tokens      INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens  INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd           REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_usage_when ON llm_usage(happened_at);
"""


class SqliteUsageLog:
    """Implementacion de UsageLog sobre SQLite."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.db_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def record(self, usage: TokenUsage, operation: str) -> float:
        """Apunta una llamada y devuelve lo que costo."""
        coste = cost_usd(usage)
        self._connection.execute(
            """
            INSERT INTO llm_usage (
                happened_at, operation, model, input_tokens, output_tokens,
                cache_read_tokens, cache_write_tokens, cost_usd
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                datetime.now(UTC).isoformat(timespec="seconds"),
                operation,
                usage.model,
                usage.input_tokens,
                usage.output_tokens,
                usage.cache_read_tokens,
                usage.cache_write_tokens,
                coste,
            ),
        )
        self._connection.commit()
        return coste

    def _totals(self, desde: str | None) -> dict[str, float]:
        condicion = "WHERE happened_at >= ?" if desde else ""
        parametros = (desde,) if desde else ()
        fila = self._connection.execute(
            f"""
            SELECT COUNT(*) AS llamadas,
                   COALESCE(SUM(input_tokens + cache_read_tokens
                                + cache_write_tokens), 0) AS entrada,
                   COALESCE(SUM(output_tokens), 0) AS salida,
                   COALESCE(SUM(cost_usd), 0) AS coste
            FROM llm_usage {condicion}
            """,  # noqa: S608 - la condicion es literal, no viene de fuera
            parametros,
        ).fetchone()
        return {clave: fila[clave] for clave in ("llamadas", "entrada", "salida", "coste")}

    def summary(self) -> dict[str, dict[str, float]]:
        ahora = datetime.now(UTC)
        return {
            "hoy": self._totals(ahora.strftime("%Y-%m-%d")),
            "este mes": self._totals(ahora.strftime("%Y-%m-01")),
            "total": self._totals(None),
        }

    def by_operation(self) -> list[sqlite3.Row]:
        """En que se va el dinero: puntuar ofertas o escribir candidaturas."""
        return self._connection.execute("""
            SELECT operation, COUNT(*) AS llamadas, SUM(cost_usd) AS coste
            FROM llm_usage GROUP BY operation ORDER BY coste DESC
            """).fetchall()
