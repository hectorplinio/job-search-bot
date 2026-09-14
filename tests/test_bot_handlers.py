"""Los handlers tienen que sobrevivir a updates incompletos.

Telegram no garantiza que un update traiga mensaje, ni que el mensaje de un
boton siga siendo accesible: uno viejo llega como "inaccessible" y no admite
respuesta. El codigo lo daba por hecho y un caso raro tumbaba el handler.

Los dobles heredan de las clases de telegram a proposito: el codigo distingue
un mensaje accesible con isinstance, asi que un doble suelto probaria otra
cosa distinta de la que corre en produccion.
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
    """Un mensaje normal: se puede responder sobre el."""

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
    """Lo que entrega Telegram cuando el mensaje del boton es viejo: trae el
    chat, pero no se puede responder sobre el."""

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
    """Un update sin mensaje acababa llamando a .reply_text sobre None."""
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
    """El caso que rompia: reply_text sobre un mensaje que no lo tiene."""
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
