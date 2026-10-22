"""Gmail REST API: fixture only, no network. Shapes mirror a real response
from gmail.googleapis.com, checked against the API docs."""

from __future__ import annotations

import base64

import pytest

from jobbot.adapters.email.gmail_source import GmailSource


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


class FakeGmailHttp:
    """Answers the token endpoint and the two Gmail endpoints this adapter
    calls, by URL - same shape as FakeHnHttp in test_hn_whoishiring.py."""

    def __init__(self, listing: dict, messages_by_id: dict[str, dict]) -> None:
        self.listing = listing
        self.messages_by_id = messages_by_id
        self.get_calls: list[str] = []
        self.post_calls: list[str] = []
        self.token_requests = 0

    async def post(self, url: str, **_kwargs):
        self.post_calls.append(url)
        self.token_requests += 1

        class _Response:
            def json(_self) -> dict:
                return {"access_token": f"fake-token-{self.token_requests}", "expires_in": 3600}

        return _Response()

    async def get_json(self, url: str, **kwargs):
        self.get_calls.append(url)
        if url.endswith("/messages"):
            return self.listing
        for message_id, payload in self.messages_by_id.items():
            if url.endswith(f"/messages/{message_id}"):
                return payload
        raise RuntimeError(f"FakeGmailHttp no tiene fixture para {url}")


LISTING = {"messages": [{"id": "m1", "threadId": "t1"}, {"id": "m2", "threadId": "t2"}]}

MESSAGE_PLAIN = {
    "id": "m1",
    "threadId": "t1",
    "snippet": "Gracias por tu interes...",
    "payload": {
        "mimeType": "text/plain",
        "headers": [
            {"name": "From", "value": "Acme Recruiting <jobs@acme.example>"},
            {"name": "Subject", "value": "Tu candidatura en Acme"},
            {"name": "Date", "value": "Tue, 13 Oct 2026 10:00:00 +0200"},
        ],
        "body": {"data": _b64("Hemos recibido tu candidatura. Gracias por tu interes.")},
    },
}

MESSAGE_MULTIPART_HTML_ONLY = {
    "id": "m2",
    "threadId": "t2",
    "snippet": "We would like to schedule an interview",
    "payload": {
        "mimeType": "multipart/alternative",
        "headers": [
            {"name": "From", "value": "Beta Corp <hr@beta.example>"},
            {"name": "Subject", "value": "Interview invitation"},
            {"name": "Date", "value": "Tue, 13 Oct 2026 11:00:00 +0200"},
        ],
        "parts": [
            {
                "mimeType": "text/html",
                "body": {"data": _b64("<p>We would like to schedule an interview.</p>")},
            }
        ],
    },
}


@pytest.fixture
def gmail_http() -> FakeGmailHttp:
    return FakeGmailHttp(LISTING, {"m1": MESSAGE_PLAIN, "m2": MESSAGE_MULTIPART_HTML_ONLY})


@pytest.mark.asyncio
async def test_busca_y_devuelve_los_dos_mensajes(gmail_http):
    source = GmailSource(
        gmail_http, client_id="id", client_secret="secret", refresh_token="refresh"
    )

    replies = await source.search("entrevista OR interview", max_results=10)

    assert {r.message_id for r in replies} == {"m1", "m2"}


@pytest.mark.asyncio
async def test_usa_el_cuerpo_de_texto_plano_cuando_existe(gmail_http):
    source = GmailSource(
        gmail_http, client_id="id", client_secret="secret", refresh_token="refresh"
    )

    replies = await source.search("q")
    m1 = next(r for r in replies if r.message_id == "m1")

    assert "Hemos recibido tu candidatura" in m1.body
    assert m1.sender == "Acme Recruiting <jobs@acme.example>"
    assert m1.subject == "Tu candidatura en Acme"


@pytest.mark.asyncio
async def test_cae_al_html_limpio_cuando_no_hay_texto_plano(gmail_http):
    source = GmailSource(
        gmail_http, client_id="id", client_secret="secret", refresh_token="refresh"
    )

    replies = await source.search("q")
    m2 = next(r for r in replies if r.message_id == "m2")

    assert "<p>" not in m2.body
    assert "We would like to schedule an interview" in m2.body


@pytest.mark.asyncio
async def test_pide_el_token_una_sola_vez_para_varias_llamadas(gmail_http):
    source = GmailSource(
        gmail_http, client_id="id", client_secret="secret", refresh_token="refresh"
    )

    await source.search("q")

    # Un listado + dos mensajes = tres llamadas autenticadas, un solo refresco.
    assert gmail_http.token_requests == 1


@pytest.mark.asyncio
async def test_un_mensaje_que_falla_no_rompe_el_resto(gmail_http):
    async def broken_get_json(url: str, **kwargs):
        if url.endswith("/messages/m1"):
            raise RuntimeError("boom")
        return await FakeGmailHttp.get_json(gmail_http, url, **kwargs)

    gmail_http.get_json = broken_get_json
    source = GmailSource(
        gmail_http, client_id="id", client_secret="secret", refresh_token="refresh"
    )

    replies = await source.search("q")

    assert {r.message_id for r in replies} == {"m2"}
