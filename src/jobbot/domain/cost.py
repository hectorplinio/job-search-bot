"""What each call to Claude costs.

The maths lives in the domain rather than the adapter because it is pure
arithmetic and worth testing without touching the API. Prices are Anthropic's
public ones, in dollars per million tokens.
"""

from __future__ import annotations

from dataclasses import dataclass

# Cache reads: 0.1x the input price. Cache writes: 1.25x.
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

# If the model is ever switched for one missing from the table, fall back to
# the most expensive rather than underestimate the bill.
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
    """The dollar cost of one call."""
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
    """Spending measured in cents does not read well with two decimals."""
    if amount == 0:
        return "0 $"
    if amount < 0.01:
        return f"{amount * 100:.2f} centavos"
    return f"{amount:.2f} $"
