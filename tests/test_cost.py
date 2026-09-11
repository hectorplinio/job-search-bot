from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from jobbot.adapters.usage_log import SqliteUsageLog
from jobbot.domain.cost import TokenUsage, cost_usd, format_cost


def test_precio_de_opus() -> None:
    # 1M de entrada son 5 $, 1M de salida son 25 $.
    assert cost_usd(TokenUsage("claude-opus-5", input_tokens=1_000_000)) == pytest.approx(5.0)
    assert cost_usd(TokenUsage("claude-opus-5", output_tokens=1_000_000)) == pytest.approx(25.0)


def test_la_cache_abarata_la_lectura() -> None:
    """Leer de cache cuesta la decima parte que enviar el token entero."""
    normal = cost_usd(TokenUsage("claude-opus-5", input_tokens=100_000))
    cacheado = cost_usd(TokenUsage("claude-opus-5", cache_read_tokens=100_000))
    assert cacheado == pytest.approx(normal * 0.1)


def test_un_modelo_desconocido_no_subestima() -> None:
    """Si se cambia de modelo y nadie actualiza la tabla, mejor pasarse que
    quedarse corto en la factura."""
    raro = cost_usd(TokenUsage("modelo-que-no-existe", input_tokens=1_000_000))
    opus = cost_usd(TokenUsage("claude-opus-5", input_tokens=1_000_000))
    assert raro == opus


def test_los_centimos_se_leen_en_centavos() -> None:
    assert format_cost(0) == "0 $"
    assert "centavos" in format_cost(0.004)
    assert format_cost(1.5) == "1.50 $"


def test_el_registro_acumula_por_periodo(tmp_path) -> None:
    log = SqliteUsageLog(tmp_path / "uso.sqlite3")
    log.record(TokenUsage("claude-opus-5", input_tokens=6_000, output_tokens=500), "puntuar")
    log.record(TokenUsage("claude-opus-5", input_tokens=4_000, output_tokens=900), "escribir")

    resumen = log.summary()
    assert resumen["hoy"]["llamadas"] == 2
    assert resumen["total"]["coste"] == pytest.approx(resumen["hoy"]["coste"])
    assert resumen["hoy"]["entrada"] == 10_000
    log.close()


def test_el_coste_se_congela_al_apuntarlo(tmp_path) -> None:
    """Se guarda el importe, no solo los tokens: si Anthropic cambia precios,
    lo ya gastado sigue contando con el precio de entonces."""
    log = SqliteUsageLog(tmp_path / "uso.sqlite3")
    apuntado = log.record(TokenUsage("claude-opus-5", input_tokens=1_000_000), "puntuar")

    import jobbot.domain.cost as modulo

    original = modulo.PRICES["claude-opus-5"]
    modulo.PRICES["claude-opus-5"] = modulo.Price(500.0, 500.0)
    try:
        assert log.summary()["total"]["coste"] == pytest.approx(apuntado)
    finally:
        modulo.PRICES["claude-opus-5"] = original
    log.close()


def test_desglosa_en_que_se_va(tmp_path) -> None:
    log = SqliteUsageLog(tmp_path / "uso.sqlite3")
    log.record(TokenUsage("claude-opus-5", output_tokens=1000), "escribir candidatura")
    log.record(TokenUsage("claude-opus-5", output_tokens=100), "puntuar ofertas")

    filas = log.by_operation()
    # Ordenado de mas caro a mas barato.
    assert [f["operation"] for f in filas] == ["escribir candidatura", "puntuar ofertas"]
    log.close()


def test_sin_llamadas_no_revienta(tmp_path) -> None:
    log = SqliteUsageLog(tmp_path / "vacio.sqlite3")
    resumen = log.summary()
    assert resumen["hoy"] == {"llamadas": 0, "entrada": 0, "salida": 0, "coste": 0}
    log.close()


def test_una_llamada_vieja_no_cuenta_como_de_hoy(tmp_path) -> None:
    log = SqliteUsageLog(tmp_path / "uso.sqlite3")
    log.record(TokenUsage("claude-opus-5", input_tokens=1000), "puntuar")
    ayer = (datetime.now(UTC) - timedelta(days=40)).isoformat(timespec="seconds")
    log._connection.execute("UPDATE llm_usage SET happened_at = ?", (ayer,))
    log._connection.commit()

    resumen = log.summary()
    assert resumen["hoy"]["llamadas"] == 0
    assert resumen["este mes"]["llamadas"] == 0
    assert resumen["total"]["llamadas"] == 1
    log.close()
