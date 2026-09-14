"""Prompts para Claude. Separados del adaptador para poder iterarlos solos.

Ninguno nombra una empresa ni una tecnologia concreta: todo sale de
`profile/cv.yaml`, asi que el bot sirve para otro perfil (frontend, datos,
mobile) cambiando ese fichero y `config.yaml`.
"""

from __future__ import annotations

from ...domain.models import JobOffer, MatchScore
from ...domain.profile import CandidateProfile

_RATING_TEMPLATE = """\
Eres el filtro de un buscador de empleo personal. Tu unico trabajo es decidir
cuanto encaja cada oferta con el perfil del candidato y explicarlo en una
frase que se leera en el movil.

Reglas:
- Puntua de 1 a 10. Un 10 es una oferta que el candidato deberia solicitar hoy.
- Se duro. La mayoria de ofertas correctas pero genericas son un 6 o un 7.
- El candidato es "{headline}". Baja la nota si el puesto es de otra
  especialidad, aunque la oferta mencione alguna de sus tecnologias.
- Baja la nota si el stack principal de la oferta queda fuera de su perfil,
  aunque liste alguna de sus tecnologias como extra.
- Sube la nota con: {stack}, remoto real y salario publicado por encima del
  objetivo.
- Si la oferta no publica salario, no la penalices por eso: dilo en concerns.
- Escribe fit_summary en espanol, maximo 25 palabras, concreto. Nada de
  "encaja bien con tu perfil": di que encaja y por que.
"""

_WRITING_TEMPLATE = """\
Escribes materiales de candidatura para {name}. Tu trabajo es que suene a esa
persona, no a plantilla.

Reglas de la cover letter:
- En ingles, siempre.
- Maximo 3 parrafos y 200 palabras en total. Mejor corta que completa.
- Sin saludo generico tipo "To whom it may concern" y sin despedida larga.
{anchors}
- Adapta el tono: con una startup, directo y de producto; con una corporacion
  o consultora, mas formal y centrado en fiabilidad y procesos.
- Nada de adjetivos vacios ("passionate", "results-driven", "team player").
- No inventes tecnologias, empresas, metricas ni titulaciones. Solo lo que
  aparece en el perfil.

Reglas del summary del CV:
- En ingles, 3 o 4 frases, en el mismo registro que el summary actual.
- Reordena para que lo primero sea lo que pide la oferta.
- Manten los hechos verificables del summary actual: no cambies cifras, anos
  ni nombres.
- No metas tecnologias que el candidato no tenga en el perfil.
"""


def rating_system(profile: CandidateProfile) -> str:
    """Instrucciones de puntuacion, construidas con el stack del perfil."""
    skills = profile.all_skills()[:14]
    return _RATING_TEMPLATE.format(
        headline=profile.headline or "el perfil del candidato",
        stack=", ".join(skills) if skills else "las tecnologias del perfil",
    )


def _anchor_lines(profile: CandidateProfile) -> str:
    """Que experiencia destacar, resuelta desde los ids del perfil."""
    anchors = profile.cover_letter_anchors
    lines: list[str] = []

    always = profile.by_id(anchors.always) if anchors.always else None
    if always is not None:
        stack = ", ".join(always.stack[:3])
        detalle = f" y su stack ({stack})" if stack else ""
        lines.append(
            f"- Menciona {always.company}{detalle}: es la experiencia mas relevante casi siempre."
        )

    for rule in anchors.when:
        experience = profile.by_id(rule.experience)
        if experience is None or not rule.keywords:
            continue
        lines.append(
            f"- Si la oferta toca {', '.join(rule.keywords)}, apoyate en {experience.company}."
        )

    if not lines:
        lines.append("- Apoyate en la experiencia mas reciente del perfil.")
    return "\n".join(lines)


def writing_system(profile: CandidateProfile) -> str:
    """Instrucciones de redaccion, con los anclajes del perfil."""
    return _WRITING_TEMPLATE.format(name=profile.name, anchors=_anchor_lines(profile))


def _offer_block(offer: JobOffer, max_chars: int = 6000) -> str:
    description = offer.description[:max_chars]
    return "\n".join(
        [
            f"Puesto: {offer.title}",
            f"Empresa: {offer.company}",
            f"Ubicacion: {offer.location or 'no indicada'}",
            f"Modalidad: {offer.work_mode.value}",
            f"Salario: {offer.salary.format()}",
            f"Fuente: {offer.source}",
            f"URL: {offer.url}",
            f"Descripcion: {description or '(la fuente no da descripcion)'}",
        ]
    )


def rating_prompt(
    candidates: list[tuple[JobOffer, MatchScore]],
    profile: CandidateProfile,
    salary_minimum: int,
    salary_target: int,
) -> str:
    blocks = []
    for index, (offer, rule_score) in enumerate(candidates):
        blocks.append(
            f"--- OFERTA {index} ---\n{_offer_block(offer, max_chars=3000)}\n"
            f"Nota preliminar por reglas: {rule_score.value}/10 "
            f"({'; '.join(rule_score.reasons)})"
        )

    return "\n\n".join(
        [
            "PERFIL DEL CANDIDATO:",
            profile.as_context(),
            "",
            f"Salario minimo aceptable: {salary_minimum} EUR brutos anuales.",
            f"Salario objetivo: {salary_target} EUR brutos anuales.",
            f"Disponibilidad: {profile.open_to}.",
            "",
            f"Evalua estas {len(candidates)} ofertas. Devuelve un veredicto por cada una,",
            "con su offer_index correspondiente y en el mismo orden.",
            "",
            *blocks,
        ]
    )


def writing_prompt(offer: JobOffer, profile: CandidateProfile) -> str:
    emphasis = profile.emphasis_for(f"{offer.title} {offer.description}")[:3]
    emphasis_hint = ", ".join(f"{item.company} ({', '.join(item.stack[:4])})" for item in emphasis)

    return "\n\n".join(
        [
            "PERFIL DEL CANDIDATO:",
            profile.as_context(),
            "",
            "OFERTA:",
            _offer_block(offer),
            "",
            f"Experiencia que mas encaja segun el stack de la oferta: {emphasis_hint}.",
            "",
            "Escribe:",
            "1. cover_letter: la carta en ingles, maximo 3 parrafos.",
            "2. cv_summary: el summary del CV reescrito en ingles para esta oferta.",
            "3. highlighted_experience: que empresas has puesto en primer plano y por que.",
            "4. detected_stack: las tecnologias que pide la oferta y el candidato tiene.",
        ]
    )
