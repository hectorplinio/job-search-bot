"""Keyword-based classification of recruiting emails, Spanish and English.

Same approach as `public_scoring.py`: a vacancy either matches or it does not,
there is no nuance worth paying an LLM for here either - a rejection email
says "no hemos podido avanzar" or it does not. Checked against real emails
from this job search (Cabify's confirmation, Shakers' rejection) before being
written, the same way the BOE/HN keyword lists were checked against real
postings.

Order matters: categories are checked most-decisive-first, so a message that
mentions both a generic "thank you for applying" and "unfortunately" is
classified as a rejection, not swallowed by the confirmation keywords every
reply tends to share.
"""

from __future__ import annotations

import re
import unicodedata

from .reply_models import ClassifiedReply, EmailReply, ReplyCategory


def _normalize(text: str) -> str:
    """Lowercase, no accents - same as public_scoring.py's normalize(), so
    'postulación' and 'postulacion' match the same keyword without having to
    spell both. Every keyword list below is written unaccented on purpose."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


# ATS platforms send on behalf of the company, so the display name is their
# own ("Greenhouse Notifications"), not the employer's - worth stripping so
# the guess is not "Greenhouse" for half of every pipeline.
_ATS_NOISE = (
    "notifications",
    "no-reply",
    "noreply",
    "talent acquisition",
    "recruiting team",
    "careers",
    "greenhouse",
    "lever",
    "ashby",
    "workday",
    "smartrecruiters",
)
_SENDER_RE = re.compile(r'^\s*"?([^"<]*?)"?\s*(?:<[^>]+>)?\s*$')


def guess_company(sender: str) -> str:
    """A best-effort company name from the "From" header. Best-effort on
    purpose: good enough to label a Telegram alert, not meant to feed
    anything that assumes it is always right."""
    match = _SENDER_RE.match(sender)
    name = (match.group(1) if match else sender).strip()
    if not name or any(marker in name.lower() for marker in _ATS_NOISE):
        email = sender[sender.find("<") + 1 : sender.find(">")] if "<" in sender else sender
        domain = email.split("@")[-1].split(".")[0] if "@" in email else ""
        return domain.capitalize()
    return name


# Each tuple is (category, keywords). Keywords are matched as plain substrings
# against lowercased text - cheap, and good enough: these are fixed phrases
# recruiting platforms and HR teams reuse almost verbatim, not free prose.
_OFFER = (
    "nos complace ofrecerte",
    "te hacemos una oferta",
    "oferta de trabajo",
    "propuesta economica",
    "bienvenido al equipo",
    "bienvenida al equipo",
    "we are pleased to offer",
    "we'd like to offer you",
    "job offer",
    "offer letter",
    "welcome to the team",
)

_INTERVIEW = (
    "entrevista",
    "te gustaria agendar",
    "disponibilidad para una llamada",
    "siguiente fase del proceso",
    "pasas a la siguiente fase",
    "schedule a call",
    "schedule an interview",
    "book a time",
    "would you be available",
    "next round",
    "technical interview",
    "hiring manager would like to speak",
    # Deliberately NOT here: "queremos conocerte" (boilerplate marketing copy
    # in application-confirmation emails, not an invite) and "move forward
    # with your application" / "move you forward" (the exact same phrase
    # shows up inside negated rejections - "we will *not* move forward with
    # your application" - so it cannot tell the two apart).
)

_REJECTED = (
    "no hemos podido avanzar",
    "hemos decidido no continuar",
    "no vamos a avanzar",
    "no continuar con tu candidatura",
    "lamentamos informarte",
    "no ha sido seleccionado",
    "no ha sido seleccionada",
    "explorar otras oportunidades",
    "no se ajusta a lo que estamos buscando",
    "hemos optado por otro perfil",
    "unfortunately",
    "we have decided not to move forward",
    "not moving forward",
    "will not be proceeding",
    "not be proceeding with your application",
    "other candidates",
    "other applicants",
    "not a match at this time",
    "we've decided to pursue other candidates",
    "more closely align with the requirements",
)

_INFO_REQUEST = (
    "necesitamos mas informacion",
    "podrias enviarnos",
    "nos faltaria",
    "podrias confirmarnos",
    "could you send us",
    "we need additional information",
    "could you confirm",
    "please provide",
)

_AUTO_CONFIRMATION = (
    "hemos recibido tu candidatura",
    "gracias por aplicar",
    "gracias por tu interes",
    "confirmamos la recepcion de tu candidatura",
    "hemos recibido tu aplicacion",
    "we have received your application",
    "thank you for applying",
    "application received",
    "talent pool",
    "your application has been received",
    "is reviewing it",
)

_NOISE = (
    "nuevas ofertas para ti",
    "ofertas recomendadas",
    "job alert",
    "jobs for you",
    "people you may know",
    "digest",
    "unsubscribe",
    "date de baja",
)

# Generated notification subjects, not human prose - a platform fires these
# the instant you click "apply", before anyone on the other end has looked at
# anything. Checked against the subject only, and checked before everything
# else: the free text in these emails' bodies often says "entrevista" or
# "interview" in passing ("si tu perfil encaja, te citaremos a una
# entrevista"), which would otherwise outrank this and misfile "I just
# applied" as "I have an interview".
_APPLICATION_SUBMITTED_SUBJECT = (
    "candidatura enviada",
    "pendiente de validacion",
    "nueva aplicacion a",
    "nuevos matches",
    "se envio tu solicitud",
    "tu solicitud fue enviada",
    "recibimos tu postulacion",
    "hemos recibido tu postulacion",
    "application sent",
    "application submitted",
    "your application has been submitted",
    "you applied to",  # LinkedIn's own "You applied to <role> at <company>"
    "your application was sent",
    "received your application",
)

_ORDER: tuple[tuple[ReplyCategory, tuple[str, ...]], ...] = (
    (ReplyCategory.OFFER, _OFFER),
    (ReplyCategory.INTERVIEW, _INTERVIEW),
    (ReplyCategory.REJECTED, _REJECTED),
    (ReplyCategory.INFO_REQUEST, _INFO_REQUEST),
    (ReplyCategory.AUTO_CONFIRMATION, _AUTO_CONFIRMATION),
    (ReplyCategory.NOISE, _NOISE),
)


def build_search_query(days_back: int) -> str:
    """A Gmail search that casts a wide net over the last `days_back` days,
    Spanish and English - the actual classification happens afterwards, on
    the full body. This only has to be broad enough not to miss a real
    reply; false positives are cheap, `classify()` sorts them into NOISE."""
    keywords = {
        *_OFFER,
        *_INTERVIEW,
        *_REJECTED,
        *_INFO_REQUEST,
        *_AUTO_CONFIRMATION,
        *_APPLICATION_SUBMITTED_SUBJECT,
    }
    terms = " OR ".join(f'"{kw}"' if " " in kw else kw for kw in sorted(keywords))
    return f"newer_than:{days_back}d ({terms}) -category:promotions -category:social"


def classify(reply: EmailReply) -> ClassifiedReply:
    text = _normalize(reply.searchable_text)
    company = guess_company(reply.sender)

    subject = _normalize(reply.subject)
    submitted = tuple(p for p in _APPLICATION_SUBMITTED_SUBJECT if p in subject)
    if submitted:
        return ClassifiedReply(
            reply=reply,
            category=ReplyCategory.AUTO_CONFIRMATION,
            matched_keywords=submitted,
            company_guess=company,
        )

    for category, keywords in _ORDER:
        matched = tuple(keyword for keyword in keywords if keyword in text)
        if matched:
            return ClassifiedReply(
                reply=reply, category=category, matched_keywords=matched, company_guess=company
            )
    return ClassifiedReply(reply=reply, category=ReplyCategory.UNKNOWN, company_guess=company)
