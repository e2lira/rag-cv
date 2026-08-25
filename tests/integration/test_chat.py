"""RFC-0005 4: contrato de `POST /v1/chat`.

Integracion porque el turno persiste en PostgreSQL y la respuesta publica el
`conversation_id` y el `message_id` que quedaron en la base: un doble de la
base probaria el doble, no el endpoint.

**El modelo es lo unico que se dobla** (RFC-0005 14, ADR-0012). El resto del
camino queda intacto: router, autenticacion, limites, el `Agent` real con sus
hooks y su prompt de sistema, la memoria y la serializacion. Doblar el agente
entero probaria el doble, no la API (P-2).
"""

import hashlib
import uuid
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from strands import Agent

from app.agent.hooks import ToolCallCapHook, ToolErrorPropagationHook, ToolStreamMarkersHook
from app.agent.prompts import SYSTEM_PROMPT
from app.api.app_factory import create_app
from app.core.engine import build_pool
from app.core.security import ApiKey
from tests.integration.agent_fixtures import (
    ScriptedModel,
    llamada_herramienta,
    make_list_cv_sections_spy,
    make_search_cv_spy,
    texto,
)

pytestmark = pytest.mark.integration

_CLAVE = "rcv_test_clave_de_prueba"
_KEY_ID = "k_read"
_FUENTE = {
    "ref": "F1",
    "chunk_id": 42,
    "unit": "Banorte -- Ingeniero de Datos Senior",
    "section": "Experiencia",
    "score": 0.031,
}
_RESPUESTA = "Ha desplegado servicios en AWS desde 2021 [F1]."


def _clave_de_prueba(*, key_id: str = _KEY_ID, role: str = "read") -> ApiKey:
    return ApiKey(
        id=key_id,
        hash=hashlib.sha256(_CLAVE.encode()).hexdigest(),
        role=role,
        label="prueba",
        expires_at=None,
        active=True,
    )


def _guion_con_busqueda() -> list[list[dict[str, Any]]]:
    """Un turno que busca en el CV y responde citando -- el caso normal."""
    return [
        llamada_herramienta("t1", "search_cv", {"query": "experiencia AWS"}),
        texto(_RESPUESTA),
    ]


def _cliente(
    database_url: str,
    *,
    guion: list[list[dict[str, Any]]] | None = None,
    claves: tuple[ApiKey, ...] | None = None,
) -> TestClient:
    app = create_app()
    app.state.db_pool = build_pool(database_url, min_size=1, max_size=2)
    app.state.api_keys = claves or (_clave_de_prueba(),)
    app.state.rate_limit_per_minute = 60
    app.state.rate_limit_per_day = 1000
    app.state.agent = Agent(
        model=ScriptedModel(guion or _guion_con_busqueda()),
        tools=[make_search_cv_spy(fuentes=[_FUENTE]), make_list_cv_sections_spy()],
        system_prompt=SYSTEM_PROMPT.format(persona="Prueba"),
        hooks=[ToolCallCapHook(), ToolErrorPropagationHook(), ToolStreamMarkersHook()],
    )
    return TestClient(app, raise_server_exceptions=False)


def test_chat_answers_with_the_contract_of_section_4(database_url: str) -> None:
    """RFC-0005 4: un turno devuelve `answer`, `sources`, `grounded`, `usage`
    y `meta`, y crea la conversacion si no venia `conversation_id`."""
    respuesta = _cliente(database_url).post(
        "/v1/chat",
        headers={"X-API-Key": _CLAVE},
        json={"message": "Que experiencia tiene desplegando en AWS?"},
    )

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()

    uuid.UUID(cuerpo["conversation_id"])  # se creo una conversacion nueva
    assert cuerpo["message_id"]
    assert cuerpo["answer"] == _RESPUESTA
    assert cuerpo["sources"] == [_FUENTE]
    assert cuerpo["grounded"] is True
    assert set(cuerpo["usage"]) == {
        "input_tokens",
        "output_tokens",
        "tool_calls",
        "cost_usd",
        "latency_ms",
    }
    assert set(cuerpo["meta"]) == {"model_id", "prompt_version", "degraded"}
    assert cuerpo["meta"]["degraded"] is False


def test_chat_persists_the_turn(database_url: str) -> None:
    """RFC-0005 4: el `message_id` publicado es el de la fila que quedo en
    `messages` -- si no persistiera, la conversacion no tendria memoria y el
    identificador no serviria para investigar un incidente (8)."""
    cuerpo = (
        _cliente(database_url)
        .post(
            "/v1/chat",
            headers={"X-API-Key": _CLAVE},
            json={"message": "Que experiencia tiene desplegando en AWS?"},
        )
        .json()
    )

    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT role, content FROM messages WHERE conversation_id = %s ORDER BY created_at",
            (cuerpo["conversation_id"],),
        )
        filas = cur.fetchall()
        cur.execute("SELECT 1 FROM messages WHERE id = %s", (cuerpo["message_id"],))
        assert cur.fetchone() is not None, "message_id no corresponde a ninguna fila"

    assert [rol for rol, _ in filas] == ["user", "assistant"]
    assert filas[1][1] == _RESPUESTA


def test_chat_rejects_an_empty_message(database_url: str) -> None:
    """RFC-0005 4 y 8: `message` vacio tras `strip()` es `400 invalid_request`,
    no un turno que gasta tokens en preguntarle al modelo por nada."""
    respuesta = _cliente(database_url).post(
        "/v1/chat", headers={"X-API-Key": _CLAVE}, json={"message": "   "}
    )

    assert respuesta.status_code == 400
    assert respuesta.json()["error"]["code"] == "invalid_request"


def test_chat_rejects_a_message_over_2000_characters(database_url: str) -> None:
    """RFC-0005 4 y 7: el tope de 2 000 caracteres es la defensa mas barata
    contra inflar el costo de tokens, y se aplica antes de invocar al agente."""
    respuesta = _cliente(database_url).post(
        "/v1/chat", headers={"X-API-Key": _CLAVE}, json={"message": "a" * 2001}
    )

    assert respuesta.status_code == 400
    assert respuesta.json()["error"]["code"] == "invalid_request"


def test_chat_without_a_key_is_401(database_url: str) -> None:
    """RFC-0005 CA-1 heredado: la ruta esta detras del rol `read`."""
    respuesta = _cliente(database_url).post("/v1/chat", json={"message": "hola"})

    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["code"] == "unauthorized"
