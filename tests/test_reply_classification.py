"""Keyword classification: fictional fixtures only, modelled on the shape of
real recruiting emails but with made-up companies and names."""

from __future__ import annotations

from datetime import UTC, datetime

from jobbot.domain.reply_classification import build_search_query, classify, guess_company
from jobbot.domain.reply_models import EmailReply, ReplyCategory


def make_reply(**overrides) -> EmailReply:
    defaults = dict(
        message_id="msg-1",
        thread_id="thread-1",
        sender="Acme Talent <talent@acme.example>",
        subject="Tu candidatura",
        snippet="",
        body="",
        received_at=datetime(2026, 10, 13, tzinfo=UTC),
    )
    defaults.update(overrides)
    return EmailReply(**defaults)


def test_rechazo_en_espanol_se_clasifica_como_rejected():
    reply = make_reply(
        body=(
            "Gracias por tu interes. Hemos decidido no continuar con tu "
            "candidatura en esta ocasion."
        )
    )
    result = classify(reply)
    assert result.category == ReplyCategory.REJECTED


def test_rejection_in_english_is_classified_as_rejected():
    reply = make_reply(
        body=(
            "Thank you for applying. Unfortunately, we will not be proceeding "
            "with your application."
        )
    )
    result = classify(reply)
    assert result.category == ReplyCategory.REJECTED


def test_rechazo_con_other_applicants_en_vez_de_other_candidates():
    """Regresion real: un rechazo de Fever decia 'move forward in the process
    with other applicants' - 'applicants', no 'candidates' - y no coincidia
    con ninguna palabra clave, asi que ni siquiera lo traia la busqueda de
    Gmail (build_search_query usa las mismas listas). No era solo un fallo de
    clasificacion, el correo era invisible para todo el sistema."""
    reply = make_reply(
        subject="Important information about your application to Fever",
        body=(
            "We received a high number of applications for this position and "
            "after careful consideration, we have decided to move forward in "
            "the process with other applicants whose skills and experience "
            "more closely align with the requirements of the role."
        ),
    )
    result = classify(reply)
    assert result.category == ReplyCategory.REJECTED


def test_invitacion_a_entrevista_en_espanol():
    reply = make_reply(body="Nos gustaria agendar una entrevista contigo la semana que viene.")
    result = classify(reply)
    assert result.category == ReplyCategory.INTERVIEW


def test_interview_invite_in_english():
    reply = make_reply(body="Would you be available for a technical interview next week?")
    result = classify(reply)
    assert result.category == ReplyCategory.INTERVIEW


def test_confirmacion_automatica_no_se_confunde_con_rechazo():
    reply = make_reply(body="Hemos recibido tu candidatura. Gracias por tu interes.")
    result = classify(reply)
    assert result.category == ReplyCategory.AUTO_CONFIRMATION
    assert result.needs_action is False


def test_rechazo_con_frase_de_confirmacion_de_por_medio_sigue_siendo_rechazo():
    """Casi todos los rechazos empiezan agradeciendo el interes - eso no debe
    tapar la palabra clave real: que se descarta la candidatura."""
    reply = make_reply(
        body=(
            "Gracias por tu interes en unirte a nuestro equipo. "
            "Hemos decidido no continuar con tu candidatura."
        )
    )
    result = classify(reply)
    assert result.category == ReplyCategory.REJECTED


def test_ruido_de_alertas_de_empleo_no_genera_aviso():
    reply = make_reply(subject="Nuevas ofertas para ti esta semana", body="job alert: 15 new jobs")
    result = classify(reply)
    assert result.category == ReplyCategory.NOISE
    assert result.needs_action is False


def test_sin_coincidencias_queda_unknown():
    reply = make_reply(body="Hola, solo escribo para saludar.")
    result = classify(reply)
    assert result.category == ReplyCategory.UNKNOWN


def test_oferta_formal_se_detecta():
    reply = make_reply(body="Nos complace ofrecerte el puesto. Bienvenido al equipo.")
    result = classify(reply)
    assert result.category == ReplyCategory.OFFER
    assert result.needs_action is True


def test_confirmacion_de_candidatura_enviada_no_se_confunde_con_entrevista():
    """Regresion real: una plataforma de empleo manda 'Nueva aplicacion a X'
    con texto de relleno que menciona 'entrevista' y 'queremos conocerte' -
    nada de eso significa que haya una entrevista de verdad, solo que se
    envio la candidatura. Encontrado corriendo el backfill de 60 dias contra
    el correo real y leyendo lo que el clasificador marcaba mal."""
    reply = make_reply(
        subject="Nueva aplicacion a Acme - Backend Engineer!!!",
        body=(
            "Tu candidatura ya esta en manos de Acme. Queremos conocerte, por eso "
            "si tu perfil encaja te citaremos a una entrevista."
        ),
    )
    result = classify(reply)
    assert result.category == ReplyCategory.AUTO_CONFIRMATION


def test_candidatura_enviada_pendiente_de_validacion_no_es_entrevista():
    reply = make_reply(
        subject="Candidatura enviada. Pendiente de validacion",
        body="Gracias por aplicar. Tu candidatura esta siendo revisada.",
    )
    result = classify(reply)
    assert result.category == ReplyCategory.AUTO_CONFIRMATION


def test_notificacion_de_linkedin_de_solicitud_enviada_no_es_entrevista():
    reply = make_reply(
        sender="LinkedIn <jobs-noreply@linkedin.com>",
        subject="You applied to Backend Engineer at Acme",
        body="Your application was sent to Acme. Entrevista con el equipo si avanza.",
    )
    result = classify(reply)
    assert result.category == ReplyCategory.AUTO_CONFIRMATION


def test_frase_ambigua_de_avance_ya_no_se_confunde_con_entrevista():
    """'move forward with your application' aparece igual en una aceptacion
    que en un rechazo negado ('we will *not* move forward...') - demasiado
    ambigua para contar como señal de entrevista por si sola."""
    reply = make_reply(body="Thank you. We will move forward with your application soon.")
    result = classify(reply)
    assert result.category != ReplyCategory.INTERVIEW


def test_guess_company_usa_el_nombre_mostrado():
    assert guess_company("Acme Recruiting <jobs@acme.example>") == "Acme Recruiting"


def test_guess_company_ignora_remitentes_de_ats_y_usa_el_dominio():
    assert guess_company("Greenhouse Notifications <no-reply@greenhouse.io>") == "Greenhouse"


def test_build_search_query_incluye_el_rango_de_dias():
    query = build_search_query(60)
    assert query.startswith("newer_than:60d (")
    assert "entrevista" in query
    assert "interview" in query
