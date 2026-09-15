"""Gross annual salary extracted from free text.

Job boards publish pay in every imaginable shape: "40.000€ - 50.000€",
"45k-55k", "2.800 € brutos/mes", "$120,000". This normalises all of it into a
yearly range and drops anything that is not plausible as a salary.
"""

from __future__ import annotations

import re

from .models import SalaryRange

# Words that confirm a line is talking about money. Without one of these we
# parse nothing from the body of a posting, or we would end up reading
# "200.000 usuarios" as if it were a salary.
SALARY_CONTEXT = (
    "salario",
    "salarial",
    "sueldo",
    "retribuci",
    "remuneraci",
    "brutos",
    "bruto",
    "salary",
    "compensation",
    "package",
    "otf",
    "€",
    "eur",
    "usd",
    "$",
    "£",
)

# A bare number (no "k", no currency symbol, no thousands separator) only
# counts as pay when the line says so explicitly. Tecnoempleo publishes things
# like "Salario:35000 a 38000 brutos anuales".
STRONG_SALARY_WORDS = (
    "salario",
    "salarial",
    "sueldo",
    "retribuci",
    "remuneraci",
    "brutos",
    "bruto",
    "salary",
    "compensation",
)

HOURLY_MARKERS = ("/h", "hora", "hour", "/día", "/dia", "per day", "diario")
MONTHLY_MARKERS = ("/mes", "mensual", "al mes", "month", "mensuales", "x 12", "x 14")

# A number with thousands separators (40.000 / 40,000), an optional decimal,
# or a bare integer. The "k" suffix and currency symbols are captured apart.
_MONEY = re.compile(
    r"(?P<pre>[€$£]|eur|usd|gbp)?\s*"
    r"(?P<num>\d{1,3}(?:[.,\s]\d{3})+|\d{2,7})"
    r"\s*(?P<k>k\b)?"
    r"\s*(?P<post>[€$£]|eur(?:os)?\b|usd\b|gbp\b)?",
    re.IGNORECASE,
)

# A yearly figure outside this band is almost certainly something else.
MIN_PLAUSIBLE = 12_000
MAX_PLAUSIBLE = 500_000

_CURRENCY_BY_SYMBOL = {
    "€": "EUR",
    "eur": "EUR",
    "euros": "EUR",
    "$": "USD",
    "usd": "USD",
    "£": "GBP",
    "gbp": "GBP",
}


def _to_int(raw: str) -> int | None:
    """'40.000' -> 40000. '40,5' -> 40 (decimals dropped)."""
    cleaned = re.sub(r"\s", "", raw)
    # It is a decimal separator only if 1-2 digits follow the last dot/comma.
    decimal = re.search(r"[.,]\d{1,2}$", cleaned)
    if decimal:
        cleaned = cleaned[: decimal.start()]
    cleaned = cleaned.replace(".", "").replace(",", "")
    return int(cleaned) if cleaned.isdigit() else None


# In "€70-100k" the k applies to both numbers. Without this we read only the
# 100k and the posting looks like it starts at 100.000 instead of 70.000. Otta
# always writes it that way.
_SHARED_K = re.compile(r"(\d{2,3})\s*-\s*(\d{2,3})\s*k\b", re.IGNORECASE)


def _expand_shared_k(text: str) -> str:
    return _SHARED_K.sub(lambda m: f"{m.group(1)}k - {m.group(2)}k", text)


def _candidates(line: str) -> tuple[list[int], str]:
    """The plausible yearly amounts in one line, plus its currency."""
    lowered = line.lower()
    if any(marker in lowered for marker in HOURLY_MARKERS):
        return [], "EUR"

    multiplier = 12 if any(marker in lowered for marker in MONTHLY_MARKERS) else 1
    explicit = any(word in lowered for word in STRONG_SALARY_WORDS)

    values: list[int] = []
    currency = "EUR"
    for match in _MONEY.finditer(line):
        symbol = (match.group("pre") or match.group("post") or "").lower().strip()
        if symbol:
            currency = _CURRENCY_BY_SYMBOL.get(symbol, currency)

        value = _to_int(match.group("num"))
        if value is None:
            continue

        has_k = bool(match.group("k"))
        if has_k:
            value *= 1000
        value *= multiplier

        # A bare number with no currency, no "k" and no thousands separator
        # (say the "5" in "5 años") only counts if the line names the salary.
        looks_like_money = (
            has_k or bool(symbol) or bool(re.search(r"[.,\s]\d{3}", match.group("num")))
        )
        if not looks_like_money and not explicit:
            continue

        if MIN_PLAUSIBLE <= value <= MAX_PLAUSIBLE:
            values.append(value)

    return values, currency


def parse_salary(text: str | None, *, require_context: bool = True) -> SalaryRange:
    """Finds a salary range in `text`.

    With `require_context=True` it only looks at lines mentioning pay or a
    currency, which is what you want for long descriptions. Pass False when
    handing it a field you already know holds the salary.
    """
    if not text:
        return SalaryRange()

    normalized = text.replace(" ", " ").replace("–", "-").replace("—", "-")
    normalized = _expand_shared_k(normalized)
    lines = [line for line in re.split(r"[\n;|]", normalized) if line.strip()]

    all_values: list[int] = []
    currency = "EUR"
    for line in lines:
        if require_context and not any(word in line.lower() for word in SALARY_CONTEXT):
            continue
        values, line_currency = _candidates(line)
        if values:
            all_values.extend(values)
            currency = line_currency

    if not all_values:
        return SalaryRange()

    low, high = min(all_values), max(all_values)
    return SalaryRange(minimum=low, maximum=high if high != low else None, currency=currency)


def from_bounds(minimum: int | None, maximum: int | None, currency: str = "EUR") -> SalaryRange:
    """Builder for sources that already give the range in separate fields."""

    def clean(value: int | None) -> int | None:
        if value is None or value <= 0:
            return None
        if value < 1000:  # some APIs publish "45" meaning 45k
            value *= 1000
        return value if MIN_PLAUSIBLE <= value <= MAX_PLAUSIBLE else None

    low, high = clean(minimum), clean(maximum)
    if low is not None and high is not None and low > high:
        low, high = high, low
    return SalaryRange(minimum=low, maximum=high, currency=currency)
