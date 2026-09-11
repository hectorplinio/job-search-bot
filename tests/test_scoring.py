from __future__ import annotations

from datetime import date, timedelta

from jobbot.domain.models import SalaryRange, WorkMode
from jobbot.domain.scoring import contains_term, score_offer

from .conftest import make_offer


def test_oferta_ideal_saca_nota_alta(criteria) -> None:
    score = score_offer(make_offer(), criteria)
    assert score.blockers == ()
    assert score.value >= 8


def test_junior_se_descarta(criteria) -> None:
    score = score_offer(make_offer(title="Junior Python Developer"), criteria)
    assert score.is_rejected
    assert any("titulo excluido" in reason for reason in score.blockers)


def test_presencial_se_descarta(criteria) -> None:
    score = score_offer(make_offer(work_mode=WorkMode.ONSITE), criteria)
    assert score.is_rejected


def test_salario_por_debajo_del_minimo_se_descarta(criteria) -> None:
    score = score_offer(make_offer(salary=SalaryRange(28_000, 34_000)), criteria)
    assert score.is_rejected
    assert any("por debajo del minimo" in reason for reason in score.blockers)


def test_cuarenta_mil_entra(criteria) -> None:
    """El usuario bajo el minimo a 40k; una oferta de 40-45k debe pasar."""
    score = score_offer(make_offer(salary=SalaryRange(40_000, 45_000)), criteria)
    assert not score.is_rejected
    assert score.value >= 6


def test_salario_desconocido_se_acepta_pero_puntua_menos(criteria) -> None:
    con_salario = score_offer(make_offer(), criteria)
    sin_salario = score_offer(make_offer(salary=SalaryRange()), criteria)
    assert not sin_salario.is_rejected
    assert sin_salario.value < con_salario.value


def test_php_sin_stack_moderno_se_descarta(criteria) -> None:
    offer = make_offer(
        title="Backend Developer PHP",
        description="Desarrollo en PHP y Laravel sobre MySQL. Backend puro.",
        salary=SalaryRange(45_000, None),
    )
    assert score_offer(offer, criteria).is_rejected


def test_php_con_python_sobrevive(criteria) -> None:
    offer = make_offer(
        title="Backend Engineer",
        description="Migramos de PHP a Python con FastAPI y PostgreSQL sobre AWS.",
    )
    assert not score_offer(offer, criteria).is_rejected


def test_oferta_de_otro_mundo_se_descarta(criteria) -> None:
    offer = make_offer(
        title="Comercial de seguros",
        description="Buscamos comercial con experiencia en venta telefonica.",
        salary=SalaryRange(45_000, None),
    )
    score = score_offer(offer, criteria)
    assert score.is_rejected
    assert any("tecnologia" in reason for reason in score.blockers)


def test_titulo_de_otro_perfil_se_descarta(criteria) -> None:
    """El caso real que se colaba: la descripcion listaba medio ecosistema y
    la oferta puntuaba 8 aunque el puesto fuese de otra cosa."""
    for title in (
        "Senior .NET Full-stack Developer",
        "Senior React Native Developer",
        "Frontend Engineer",
        "Data Scientist",
    ):
        score = score_offer(make_offer(title=title), criteria)
        assert score.is_rejected, title
        assert any("otro perfil" in reason for reason in score.blockers), title


def test_titulo_mixto_sobrevive_si_nombra_el_stack(criteria) -> None:
    # "Python/PHP Backend Developer" si es candidato: el titulo nombra Python.
    score = score_offer(make_offer(title="Backend Developer Python / PHP"), criteria)
    assert not score.is_rejected


def test_oferta_caducada_se_descarta(criteria) -> None:
    old = date.today() - timedelta(days=criteria.search.max_age_days + 5)
    assert score_offer(make_offer(posted_at=old), criteria).is_rejected


def test_hibrido_se_descarta(criteria) -> None:
    """Vive lejos de una capital: un hibrido en Madrid no le sirve."""
    score = score_offer(make_offer(work_mode=WorkMode.HYBRID), criteria)
    assert score.is_rejected
    assert any("hybrid" in reason for reason in score.blockers)


def test_remoto_puntua_mas_que_sin_especificar(criteria) -> None:
    remoto = score_offer(make_offer(work_mode=WorkMode.REMOTE), criteria)
    sin_saber = score_offer(make_offer(work_mode=WorkMode.UNKNOWN), criteria)
    assert remoto.value > sin_saber.value


def test_titulo_de_java_se_descarta(criteria) -> None:
    """Se colo un "Senior Java & React Developer": el patron pedia
    "java developer" y ese titulo no lo tiene."""
    score = score_offer(make_offer(title="Senior Java & React Developer"), criteria)
    assert score.is_rejected

    # Pero "java" no puede casar dentro de "javascript".
    js = score_offer(make_offer(title="Backend Developer JavaScript"), criteria)
    assert not js.is_rejected


def test_limites_de_palabra() -> None:
    # "go" no debe casar dentro de "django", ni "aws" dentro de "awsome".
    assert contains_term("we use django", "go") is False
    assert contains_term("node.js and typescript", "node.js") is True
    assert contains_term("stack asp.net legacy", ".net") is True


def test_remoto_pero_solo_dentro_de_eeuu_se_descarta(criteria) -> None:
    """Son remotas de verdad, pero no las puede aceptar desde Espana."""
    offer = make_offer(
        title="Senior Backend Engineer",
        description=(
            "Fully remote role. Python, PostgreSQL and AWS. "
            "Note: this position is USA Only and you must be authorized to work in the US."
        ),
    )
    score = score_offer(offer, criteria)
    assert score.is_rejected
    assert any("texto excluido" in reason for reason in score.blockers)


def test_remota_mundial_sigue_entrando(criteria) -> None:
    offer = make_offer(
        title="Senior Backend Engineer",
        description="Fully remote, anywhere in the world. Python, PostgreSQL, AWS, Kubernetes.",
    )
    assert not score_offer(offer, criteria).is_rejected
