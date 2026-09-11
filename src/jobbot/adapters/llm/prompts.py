"""Prompts para Claude. Separados del adaptador para poder iterarlos solos."""

from __future__ import annotations

from ...domain.models import JobOffer, MatchScore
from ...domain.profile import CandidateProfile

RATING_SYSTEM = """\
Eres el filtro de un buscador de empleo personal. Tu unico trabajo es decidir
cuanto encaja cada oferta con el perfil del candidato y explicarlo en una
frase que se leera en el movil.

Reglas:
- Puntua de 1 a 10. Un 10 es una oferta que el candidato deberia solicitar hoy.
- Se duro. La mayoria de ofertas correctas pero genericas son un 6 o un 7.
- Baja la nota si el puesto es de otro perfil (data science puro, devops puro,
  frontend puro, SRE) aunque mencione Python.
- Baja la nota si el stack principal esta fuera del perfil (PHP, .NET, Java
  puro) aunque la oferta liste Python como extra.
- Sube la nota con: Python o Node/TypeScript como stack principal,
  microservicios, arquitectura hexagonal, TDD, Kubernetes, PostgreSQL, AWS,
  Kafka, remoto real y salario publicado por encima del objetivo.
- Si la oferta no publica salario, no la penalices por eso: dilo en concerns.
- Escribe fit_summary en espanol, maximo 25 palabras, concreto. Nada de
  "encaja bien con tu perfil": di que encaja y por que.
"""

WRITING_SYSTEM = """\
Escribes materiales de candidatura para un ingeniero de software. Tu trabajo
es que suene a el, no a plantilla.

Reglas de la cover letter:
- En ingles, siempre.
- Maximo 3 parrafos y 200 palabras en total. Mejor corta que completa.
- Sin saludo generico tipo "To whom it may concern" y sin despedida larga.
- Menciona AscendGate y los microservicios en Kubernetes: es el trabajo
  actual y el mas relevante casi siempre.
- Si la oferta toca IA, LLMs, OpenAI o NLP, menciona el trabajo en Telefonica
  integrando modelos de OpenAI para el catalogo de Movistar.
- Si la oferta es de Node.js o TypeScript, apoya en Jobandtalent y Devaway.
- Adapta el tono: con una startup, directo y de producto; con una corporacion
  o consultora, mas formal y centrado en fiabilidad y procesos.
- Nada de adjetivos vacios ("passionate", "results-driven", "team player").
- No inventes tecnologias, empresas, metricas ni titulaciones. Solo lo que
  aparece en el perfil.

Reglas del summary del CV:
- En ingles, 3 o 4 frases, en el mismo registro que el summary actual.
- Reordena para que lo primero sea lo que pide la oferta.
- Mantiene los hechos verificables del summary actual (5+ anos, arquitectura
  hexagonal, microservicios event-driven, 100% cobertura).
- No metas tecnologias que el candidato no tenga en el perfil.
"""


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
