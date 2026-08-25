"""RFC-0005 5, CA-11: orden de eventos de `POST /v1/chat/stream`.

**El orden se afirma sobre el flujo recibido, nunca sobre tiempos**
(RFC-0005 14, P-7). Nada de `sleep` para "esperar a que llegue": eso produce
intermitencia y se acaba desactivando, que es peor que no tener la prueba.

Integracion, y con el mismo `ScriptedModel` que `/v1/chat`: si las dos
superficies no consumieran el mismo flujo del agente podrian divergir sin que
nada fallara, y RFC-0005 13 declara esa divergencia un defecto.
"""

import json
from typing import Any

import pytest

from tests.integration.test_chat import _CLAVE, _FUENTE, _RESPUESTA, _cliente

pytestmark = pytest.mark.integration


def _eventos(texto_sse: str) -> list[tuple[str, dict[str, Any]]]:
    """Parte el flujo SSE en (nombre, datos), respetando los comentarios.

    Las lineas que empiezan por `:` son comentarios de mantenimiento -- el
    `: ping` de RFC-0005 5 -- y no son eventos: contarlos como tales haria
    fallar el orden por una linea que existe justo para no molestar.
    """
    eventos = []
    for bloque in texto_sse.split("\n\n"):
        nombre, datos = None, None
        for linea in bloque.splitlines():
            if linea.startswith(":"):
                continue
            if linea.startswith("event:"):
                nombre = linea[len("event:") :].strip()
            elif linea.startswith("data:"):
                datos = json.loads(linea[len("data:") :].strip())
        if nombre is not None:
            eventos.append((nombre, datos or {}))
    return eventos


def _flujo(database_url: str) -> tuple[Any, list[tuple[str, dict[str, Any]]]]:
    respuesta = _cliente(database_url).post(
        "/v1/chat/stream",
        headers={"X-API-Key": _CLAVE},
        json={"message": "Que experiencia tiene desplegando en AWS?"},
    )
    return respuesta, _eventos(respuesta.text)


def test_event_order(database_url: str) -> None:
    """CA-11: `start`, >=1 `token`, `sources` y `done`, en ese orden."""
    respuesta, eventos = _flujo(database_url)

    assert respuesta.status_code == 200, respuesta.text
    nombres = [n for n, _ in eventos]

    assert nombres[0] == "start", nombres
    assert nombres[-1] == "done", nombres
    assert nombres.count("token") >= 1, nombres
    assert nombres.index("sources") < nombres.index("done"), nombres
    assert nombres.index("start") < nombres.index("token"), nombres
    assert nombres.index("token") < nombres.index("sources"), nombres


def test_the_stream_is_not_buffered(database_url: str) -> None:
    """RFC-0005 5: `text/event-stream` sin buffering intermedio.

    Sin `X-Accel-Buffering: no`, nginx acumula la respuesta y la entrega de
    golpe al final: el flujo sigue siendo correcto y el streaming deja de
    existir, sin que nada falle. Es el fallo silencioso que RNF-1 no ve.
    """
    respuesta, _ = _flujo(database_url)

    assert respuesta.headers["content-type"].startswith("text/event-stream")
    assert respuesta.headers["x-accel-buffering"] == "no"
    assert respuesta.headers["cache-control"] == "no-cache"


def test_start_identifies_the_turn(database_url: str) -> None:
    """RFC-0005 5: `start` lleva `conversation_id` y `message_id`.

    Van al principio y no al final a proposito: un cliente que aborta a
    mitad del flujo necesita poder nombrar el turno que abandono."""
    _, eventos = _flujo(database_url)
    _, datos = eventos[0]

    assert set(datos) == {"conversation_id", "message_id"}
    assert datos["conversation_id"]
    assert datos["message_id"]


def test_sources_and_done_carry_the_contract(database_url: str) -> None:
    """RFC-0005 5: `sources` lleva las fuentes y `done` el consumo del turno.

    Es lo que hace util el flujo frente a `/v1/chat`: el cliente que solo
    escucha `done` tiene la contabilidad sin repetir la pregunta."""
    _, eventos = _flujo(database_url)
    por_nombre = {n: d for n, d in eventos}

    assert por_nombre["sources"]["sources"] == [_FUENTE]
    assert por_nombre["done"]["grounded"] is True
    assert set(por_nombre["done"]["usage"]) == {
        "input_tokens",
        "output_tokens",
        "tool_calls",
        "cost_usd",
        "latency_ms",
    }


def test_the_streamed_answer_matches_the_tokens(database_url: str) -> None:
    """Los `token` concatenados son la respuesta -- no un resumen ni una
    version distinta de la que devuelve `/v1/chat` (RFC-0005 13)."""
    _, eventos = _flujo(database_url)

    texto = "".join(d["text"] for n, d in eventos if n == "token")

    assert texto == _RESPUESTA


def test_stream_without_a_key_is_401(database_url: str) -> None:
    """RFC-0005 6.3: el flujo esta detras del rol `read`, como `/v1/chat`."""
    respuesta = _cliente(database_url).post("/v1/chat/stream", json={"message": "hola"})

    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["code"] == "unauthorized"
