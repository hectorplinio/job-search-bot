"""Cuanto cuesta cada llamada a Claude.

El calculo vive en el dominio y no en el adaptador porque es aritmetica pura
y conviene poder probarla sin tocar la API. Los precios son los publicos de
Anthropic, en dolares por millon de tokens.
"""

from __future__ import annotations

from dataclasses import dataclass

# Lectura de cache: 0,1x el precio de entrada. Escritura: 1,25x.
CACHE_READ_FACTOR = 0.1
CACHE_WRITE_FACTOR = 1.25


@dataclass(frozen=True, slots=True)
class Price:
    input_per_million: float
    output_per_million: float


PRICES: dict[str, Price] = {
    "claude-opus-5": Price(5.0, 25.0),
    "claude-sonnet-5": Price(2.0, 10.0),
    "claude-haiku-4-5": Price(1.0, 5.0),
}

# Si algun dia se cambia de modelo y no esta en la tabla, se tira del mas caro
# antes que subestimar la factura.
FALLBACK = PRICES["claude-opus-5"]


@dataclass(frozen=True, slots=True)
class TokenUsage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )


def cost_usd(usage: TokenUsage) -> float:
    """Coste en dolares de una llamada."""
    price = PRICES.get(usage.model, FALLBACK)
    entrada = price.input_per_million / 1_000_000
    salida = price.output_per_million / 1_000_000

    return (
        usage.input_tokens * entrada
        + usage.output_tokens * salida
        + usage.cache_read_tokens * entrada * CACHE_READ_FACTOR
        + usage.cache_write_tokens * entrada * CACHE_WRITE_FACTOR
    )


def format_cost(amount: float) -> str:
    """Un gasto de centimos no se lee bien con dos decimales."""
    if amount == 0:
        return "0 $"
    if amount < 0.01:
        return f"{amount * 100:.2f} centavos"
    return f"{amount:.2f} $"
