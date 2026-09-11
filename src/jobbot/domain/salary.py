"""Extraccion de salario anual bruto a partir de texto libre.

Las fuentes publican el salario de cualquier manera imaginable: "40.000€ -
50.000€", "45k-55k", "2.800 € brutos/mes", "$120,000". Esto lo normaliza todo
a un rango anual y descarta lo que no es plausible como salario.
"""

from __future__ import annotations

import re

from .models import SalaryRange

# Palabras que confirman que una linea habla de dinero. Sin una de estas no
# parseamos nada del cuerpo de la oferta, o acabariamos leyendo "200.000
# usuarios" como si fuera un sueldo.
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

# Un numero pelado (sin "k", sin simbolo, sin separador de miles) solo cuenta
# como salario si la linea lo dice explicitamente. Tecnoempleo publica cosas
# como "Salario:35000 a 38000 brutos anuales".
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

# Numero con separadores de miles (40.000 / 40,000), decimal opcional, o
# entero pelado. El sufijo "k" y los simbolos de moneda se capturan aparte.
_MONEY = re.compile(
    r"(?P<pre>[€$£]|eur|usd|gbp)?\s*"
    r"(?P<num>\d{1,3}(?:[.,\s]\d{3})+|\d{2,7})"
    r"\s*(?P<k>k\b)?"
    r"\s*(?P<post>[€$£]|eur(?:os)?\b|usd\b|gbp\b)?",
    re.IGNORECASE,
)

# Un salario anual fuera de esta horquilla es casi seguro otra cosa.
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
    """'40.000' -> 40000. '40,5' -> 40 (decimales fuera)."""
    cleaned = re.sub(r"\s", "", raw)
    # Separador decimal solo si quedan 1-2 digitos detras del ultimo punto/coma.
    decimal = re.search(r"[.,]\d{1,2}$", cleaned)
    if decimal:
        cleaned = cleaned[: decimal.start()]
    cleaned = cleaned.replace(".", "").replace(",", "")
    return int(cleaned) if cleaned.isdigit() else None


# En "€70-100k" la k vale para los dos numeros. Sin esto se lee solo el 100k
# y la oferta parece tener suelo de 100.000 en vez de 70.000. Otta lo escribe
# siempre asi.
_SHARED_K = re.compile(r"(\d{2,3})\s*-\s*(\d{2,3})\s*k\b", re.IGNORECASE)


def _expand_shared_k(text: str) -> str:
    return _SHARED_K.sub(lambda m: f"{m.group(1)}k - {m.group(2)}k", text)


def _candidates(line: str) -> tuple[list[int], str]:
    """Devuelve los importes anuales plausibles de una linea y su moneda."""
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

        # Un numero pelado sin moneda, sin "k" y sin separador de miles
        # (p.ej. "5" de "5 años") solo cuenta si la linea nombra el salario.
        looks_like_money = (
            has_k or bool(symbol) or bool(re.search(r"[.,\s]\d{3}", match.group("num")))
        )
        if not looks_like_money and not explicit:
            continue

        if MIN_PLAUSIBLE <= value <= MAX_PLAUSIBLE:
            values.append(value)

    return values, currency


def parse_salary(text: str | None, *, require_context: bool = True) -> SalaryRange:
    """Busca un rango salarial en `text`.

    Con `require_context=True` solo mira las lineas que mencionan salario o
    una moneda, que es lo correcto para descripciones largas. Ponlo a False
    cuando le pases un campo que ya sabes que es el salario.
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
    """Constructor para fuentes que ya dan el rango en campos separados."""

    def clean(value: int | None) -> int | None:
        if value is None or value <= 0:
            return None
        if value < 1000:  # algunas APIs publican "45" queriendo decir 45k
            value *= 1000
        return value if MIN_PLAUSIBLE <= value <= MAX_PLAUSIBLE else None

    low, high = clean(minimum), clean(maximum)
    if low is not None and high is not None and low > high:
        low, high = high, low
    return SalaryRange(minimum=low, maximum=high, currency=currency)
