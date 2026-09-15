"""The handlers have to survive incomplete updates.

Telegram guarantees neither that an update carries a message, nor that a
button's message is still accessible: an old one arrives as "inaccessible"
and takes no reply. The code assumed otherwise and one odd case took the
handler down.

The doubles subclass telegram's own classes on purpose: the code tells an
accessible message apart with isinstance, so a loose double would test
something other than what runs in production.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import pytest
from telegram import Chat, Message

from jobbot import bot as bot_module

RESPUESTAS: list[str] = []
ACCIONES: list[str] = []


class ChatDePrueba(Chat):
    async def send_action(self, action: str, **kwargs: Any) -> bool:
        ACCIONES.append(str(action))
        return True


class MensajeDePrueba(Message):
    """A normal message: you can reply on it."""

    async def reply_text(self, text: str, **kwargs: Any) -> Any:
        RESPUESTAS.append(text)
        return self


def mensaje(text: str = "") -> MensajeDePrueba:
    return MensajeDePrueba(
        message_id=1,
        date=dt.datetime.now(dt.UTC),
        chat=ChatDePrueba(id=42, type=Chat.PRIVATE),
        text=text or None,
    )


@dataclass
class MensajeInaccesible:
    """What Telegram delivers when the button's message is old: it carries
    the chat, but you cannot reply on it."""

    chat: Any = None


@dataclass
class FakeQuery:
    data: str | None = "cover:abc123"
    message: Any = None
    contestado: bool = False

    async def answer(self) -> None:
        self.contestado = True


@dataclass
class FakeBot:
    enviados: list[tuple[int, str]] = field(default_factory=list)

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> None:
        self.enviados.append((chat_id, text))


@dataclass
class FakeUpdate:
    effective_message: Any = None
    callback_query: Any = None


class FakeContext:
    def __init__(self, container: Any = None) -> None:
        self.bot = FakeBot()
        self.application = type("App", (), {"bot_data": {"container": container}})()
        self.args: list[str] = []


class FakeContainer:
    def __init__(self, encontrado: Any = None) -> None:
        self.repository = type(
            "Repo", (), {"find_by_fingerprint_prefix": lambda self, prefix: encontrado}
        )()


@pytest.fixture(autouse=True)
def _limpiar() -> None:
    RESPUESTAS.clear()
    ACCIONES.clear()


async def test_un_update_sin_mensaje_no_revienta() -> None:
    """An update with no message ended up calling .reply_text on None."""
    await bot_module.free_text(FakeUpdate(), FakeContext())
    assert RESPUESTAS == []


async def test_un_callback_sin_query_no_revienta() -> None:
    await bot_module.button(FakeUpdate(), FakeContext())
    assert RESPUESTAS == []


async def test_una_oferta_que_ya_no_esta_se_avisa_en_el_mensaje() -> None:
    update = FakeUpdate(callback_query=FakeQuery(message=mensaje()))
    context = FakeContext(FakeContainer(encontrado=None))

    await bot_module.button(update, context)

    assert update.callback_query.contestado is True
    assert "ya no esta en el historial" in RESPUESTAS[0]
    assert context.bot.enviados == []


async def test_si_el_mensaje_del_boton_es_inaccesible_responde_por_el_chat() -> None:
    """The case that broke: reply_text on a message that does not have it."""
    inaccesible = MensajeInaccesible(chat=ChatDePrueba(id=42, type=Chat.PRIVATE))
    update = FakeUpdate(callback_query=FakeQuery(message=inaccesible))
    context = FakeContext(FakeContainer(encontrado=None))

    await bot_module.button(update, context)

    assert RESPUESTAS == []
    assert context.bot.enviados == [(42, "Esa oferta ya no esta en el historial.")]


@pytest.mark.parametrize("texto", ["", "hola"])
async def test_el_texto_corto_sin_enlace_pide_una_oferta(texto: str) -> None:
    await bot_module.free_text(FakeUpdate(effective_message=mensaje(texto)), FakeContext())
    assert "Mandame el enlace" in RESPUESTAS[0]
