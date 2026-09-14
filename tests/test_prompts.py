"""Los prompts salen del perfil, no de constantes.

Antes el prompt de redaccion nombraba AscendGate, Telefonica y Jobandtalent,
asi que otra persona que clonase el repo recibia cartas sobre los trabajos de
otro. Estos tests fijan que el bot es reutilizable.
"""

from __future__ import annotations

from pathlib import Path

from jobbot.adapters.llm.prompts import rating_system, writing_system
from jobbot.domain.profile import CandidateProfile

RAIZ = Path(__file__).resolve().parents[1]
MIO = RAIZ / "profile" / "cv.yaml"
OTRO = RAIZ / "examples" / "frontend" / "cv.yaml"


def test_las_instrucciones_nombran_las_empresas_del_perfil() -> None:
    texto = writing_system(CandidateProfile.load(OTRO))
    assert "Mapamundi" in texto
    assert "Ada Ejemplo" in texto
    for ajeno in ("AscendGate", "Ascend Makers", "Telefonica", "Jobandtalent"):
        assert ajeno not in texto


def test_cada_perfil_produce_instrucciones_distintas() -> None:
    assert writing_system(CandidateProfile.load(MIO)) != writing_system(CandidateProfile.load(OTRO))
    assert rating_system(CandidateProfile.load(MIO)) != rating_system(CandidateProfile.load(OTRO))


def test_los_anclajes_condicionales_llegan_al_prompt() -> None:
    texto = writing_system(CandidateProfile.load(OTRO))
    assert "accessibility" in texto
    assert "Tienda Verde" in texto


def test_la_puntuacion_usa_el_titular_y_el_stack_del_perfil() -> None:
    perfil = CandidateProfile.load(OTRO)
    texto = rating_system(perfil)
    assert "Frontend Software Engineer" in texto
    assert "React" in texto
    assert "Python" not in texto


def test_un_perfil_sin_anclajes_no_deja_el_prompt_a_medias() -> None:
    perfil = CandidateProfile(name="Sin Anclajes", headline="Backend Engineer")
    texto = writing_system(perfil)
    assert "experiencia mas reciente" in texto
    assert "{anchors}" not in texto
