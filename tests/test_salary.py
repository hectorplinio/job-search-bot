from __future__ import annotations

import pytest

from jobbot.domain.salary import from_bounds, parse_salary


@pytest.mark.parametrize(
    ("text", "expected_min", "expected_max"),
    [
        ("Salario: 40.000€ - 50.000€ brutos anuales", 40_000, 50_000),
        ("Banda salarial 45k-55k", 45_000, 55_000),
        ("Salary: €50,000 - €65,000", 50_000, 65_000),
        ("Salario:35000 a 38000 brutos anuales", 35_000, 38_000),
        ("50.000 € - 56.000 € Bruto/año", 50_000, 56_000),
        ("Retribucion: 2.800 € brutos/mes", 33_600, None),
        # Otta escribe la k una sola vez para los dos extremos del rango.
        ("€70-100k", 70_000, 100_000),
        ("$120-160k", 120_000, 160_000),
    ],
)
def test_extrae_rangos_habituales(text: str, expected_min: int, expected_max: int | None) -> None:
    salary = parse_salary(text)
    assert salary.minimum == expected_min
    assert salary.maximum == expected_max


@pytest.mark.parametrize(
    "text",
    [
        "Buscamos alguien con 5 años de experiencia",
        "Gestionamos 200 clientes al mes",
        "Tarifa de 45 €/hora para freelance",
        "",
    ],
)
def test_no_inventa_salarios(text: str) -> None:
    assert parse_salary(text).is_known is False


def test_ignora_numeros_fuera_de_lineas_de_salario() -> None:
    text = "Nuestra plataforma procesa 250.000 eventos al dia y el equipo son 12 personas."
    assert parse_salary(text).is_known is False


def test_moneda_detectada() -> None:
    assert parse_salary("Compensation: $120,000 - $150,000").currency == "USD"


def test_from_bounds_normaliza_miles() -> None:
    # Manfred publica "50" queriendo decir 50.000 en la ficha de detalle.
    salary = from_bounds(50, 60)
    assert (salary.minimum, salary.maximum) == (50_000, 60_000)


def test_from_bounds_descarta_valores_imposibles() -> None:
    assert from_bounds(0, 0).is_known is False


def test_formato_legible() -> None:
    assert from_bounds(40_000, 50_000).format() == "40.000€ - 50.000€"
    assert from_bounds(None, None).format() == "no publicado"
