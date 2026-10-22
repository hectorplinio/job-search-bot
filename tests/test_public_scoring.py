"""Scoring oposiciones: elegibility, urgency and the promocion-interna veto."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from jobbot.domain.criteria import PublicCriteria
from jobbot.domain.public_models import Ambito, Grupo, Oposicion, TipoPlaza, Turno
from jobbot.domain.public_scoring import business_days_after, score_oposicion


def make_oposicion(**overrides) -> Oposicion:
    defaults = dict(
        fuente="boe",
        identificador="BOE-A-2026-1",
        titulo="Convocatoria de plazas de programador para el ayuntamiento de Villena",
        organismo="Ayuntamiento de Villena",
        url="https://example.com/1",
        fecha_publicacion=date(2026, 10, 6),
        ambito=Ambito.LOCAL,
        grupo=Grupo.C1,
        turno=Turno.LIBRE,
        tipo_plaza=TipoPlaza.FIJA,
        ubicacion="Villena",
        fecha_limite_aproximada=date.today() + timedelta(days=10),
    )
    defaults.update(overrides)
    return Oposicion(**defaults)


@pytest.fixture
def criteria() -> PublicCriteria:
    # The real towns live in .env; these tests bring their own.
    return PublicCriteria(priority_locations=["villena"])


def test_c1_turno_libre_en_ambito_prioritario_es_urgente(criteria):
    oposicion = make_oposicion()
    score = score_oposicion(oposicion, criteria)

    assert score.urgent is True
    assert score.is_rejected is False


def test_a1_turno_libre_se_puntua_pero_no_elegible(criteria):
    oposicion = make_oposicion(
        titulo=(
            "Convocatoria Cuerpo Superior de Sistemas y Tecnologias de la "
            "Informacion, Grupo A1, turno libre"
        ),
        grupo=Grupo.A1,
    )
    score = score_oposicion(oposicion, criteria)

    assert score.is_rejected is False
    assert any("NO ELEGIBLE" in reason for reason in score.reasons)
    # Se sigue notificando (no es un blocker), pero con menos puntos.
    sin_penalizacion = score_oposicion(make_oposicion(grupo=Grupo.C1), criteria)
    assert score.value < sin_penalizacion.value


def test_promocion_interna_se_descarta(criteria):
    oposicion = make_oposicion(turno=Turno.PROMOCION_INTERNA)
    score = score_oposicion(oposicion, criteria)

    assert score.is_rejected is True


def test_fuera_de_ambito_prioritario_no_es_urgente(criteria):
    oposicion = make_oposicion(organismo="Ayuntamiento de Soria", ubicacion="Soria")
    score = score_oposicion(oposicion, criteria)

    assert score.urgent is False


def test_sin_palabra_clave_tic_se_descarta(criteria):
    oposicion = make_oposicion(titulo="Convocatoria de plazas de bombero para Villena")
    score = score_oposicion(oposicion, criteria)

    assert score.is_rejected is True


def test_estado_fuera_de_cuerpos_tic_configurados_se_descarta(criteria):
    oposicion = make_oposicion(
        titulo="Convocatoria de informatica para la Administracion General del Estado",
        ambito=Ambito.ESTADO,
        organismo="Ministerio de Hacienda",
        ubicacion="",
    )
    score = score_oposicion(oposicion, criteria)

    assert score.is_rejected is True


def test_business_days_after_salta_fines_de_semana():
    # 2026-10-06 es martes.
    limite = business_days_after(date(2026, 10, 6), 5)
    # 5 dias habiles desde un martes: mie, jue, vie, (sab, dom saltados), lun -> 2026-10-13
    assert limite == date(2026, 10, 13)
