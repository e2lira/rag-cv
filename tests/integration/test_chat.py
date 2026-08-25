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
import json
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


class _FabricaDePrueba:
    """El reparto de ADR-0017: **un modelo compartido, un agente por turno**.

    La prueba monta el mismo reparto que produccion y no uno propio. Si
    compartiera el agente -- que es lo que hacia antes de ADR-0017 -- no
    podria detectar la fuga que ADR-0017 corrige: el doble tendria el mismo
    defecto que el codigo, y las dos mentiras se cancelarian.

    El modelo se guarda accesible a proposito: lo que estas pruebas
    verifican es **lo que el modelo recibe** (RFC-0014 P-13), y para eso hay
    que poder preguntarle.
    """

    def __init__(self, guion: list[list[dict[str, Any]]]) -> None:
        self.model = ScriptedModel(guion)

    def for_turn(self, messages: list[dict[str, Any]] | None = None) -> Agent:
        return Agent(
            model=self.model,
            messages=list(messages or []),
            tools=[make_search_cv_spy(fuentes=[_FUENTE]), make_list_cv_sections_spy()],
            system_prompt=SYSTEM_PROMPT.format(persona="Prueba"),
            hooks=[ToolCallCapHook(), ToolErrorPropagationHook(), ToolStreamMarkersHook()],
        )


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
    app.state.agent_factory = _FabricaDePrueba(guion or _guion_con_busqueda())
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


def test_a_conversation_of_another_key_is_404(database_url: str) -> None:
    """CA-8: una conversacion ajena devuelve `404`, **no `403`**.

    La diferencia no es cosmetica. Un `403` dice "existe, pero no es tuya",
    y eso ya es informacion sobre las conversaciones de otro: con el
    identificador se puede sondear cuales existen. El `404` es
    indistinguible de una conversacion que nunca existio.
    """
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO conversations (key_id) VALUES ('k_ajena') RETURNING id")
        fila = cur.fetchone()
        assert fila is not None
        ajena = str(fila[0])
        conn.commit()

    respuesta = _cliente(database_url).post(
        "/v1/chat",
        headers={"X-API-Key": _CLAVE},
        json={"message": "Que experiencia tiene?", "conversation_id": ajena},
    )

    assert respuesta.status_code == 404, respuesta.text
    assert respuesta.json()["error"]["code"] == "not_found"


def test_an_unknown_conversation_is_404_too(database_url: str) -> None:
    """CA-8, la otra mitad: inexistente y ajena responden **igual**.

    Si difirieran -- en codigo, en mensaje o en tiempo -- la diferencia
    seria el oraculo que el `404` existe para cerrar.
    """
    inexistente = str(uuid.uuid4())

    respuesta = _cliente(database_url).post(
        "/v1/chat",
        headers={"X-API-Key": _CLAVE},
        json={"message": "Que experiencia tiene?", "conversation_id": inexistente},
    )

    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["code"] == "not_found"


def test_a_conversation_of_the_same_key_continues(database_url: str) -> None:
    """CA-8 no puede cumplirse cerrandolo todo: la conversacion **propia**
    sigue, y el turno nuevo se anade a la misma."""
    cliente = _cliente(database_url, guion=[*_guion_con_busqueda(), *_guion_con_busqueda()])
    primero = cliente.post(
        "/v1/chat", headers={"X-API-Key": _CLAVE}, json={"message": "Primera pregunta"}
    ).json()

    segundo = cliente.post(
        "/v1/chat",
        headers={"X-API-Key": _CLAVE},
        json={"message": "Segunda pregunta", "conversation_id": primero["conversation_id"]},
    )

    assert segundo.status_code == 200, segundo.text
    assert segundo.json()["conversation_id"] == primero["conversation_id"]


def _texto_de_los_mensajes(cliente: TestClient) -> str:
    """Todo lo que el modelo recibio en su ULTIMA invocacion.

    Se mira lo que el modelo **recibe**, no lo que la API devuelve: que dos
    turnos compartan `conversation_id` no prueba que el segundo vea al
    primero -- el identificador puede coincidir y el historial no viajar.
    Esa distincion es justo lo que RFC-0004 7 exige.
    """
    fabrica: _FabricaDePrueba = cliente.app.state.agent_factory  # type: ignore[attr-defined,union-attr]
    return json.dumps(fabrica.model.stream_calls[-1]["messages"], ensure_ascii=False, default=str)


def test_the_second_turn_sees_the_first(database_url: str) -> None:
    """RFC-0004 7: en cada turno se carga el historial de esa conversacion.

    Sin esto la conversacion no existe: se persiste, se le devuelve al
    cliente un `conversation_id`, y cada pregunta llega al modelo como si
    fuera la primera. El sintoma en produccion es un agente que no recuerda
    lo que acaba de decir.
    """
    cliente = _cliente(database_url, guion=[*_guion_con_busqueda(), *_guion_con_busqueda()])
    primero = cliente.post(
        "/v1/chat", headers={"X-API-Key": _CLAVE}, json={"message": "Trabajo en AWS?"}
    ).json()

    cliente.post(
        "/v1/chat",
        headers={"X-API-Key": _CLAVE},
        json={"message": "Y en que anio?", "conversation_id": primero["conversation_id"]},
    )

    recibido = _texto_de_los_mensajes(cliente)
    assert "Trabajo en AWS?" in recibido, "el modelo no vio la pregunta anterior"
    assert _RESPUESTA in recibido, "el modelo no vio su propia respuesta anterior"


def test_another_conversation_sees_nothing_of_the_first(database_url: str) -> None:
    """La guarda del test anterior, y no es opcional.

    Cargar historial mal -- dejandolo en el agente compartido en vez de
    pasarlo por invocacion -- haria pasar la continuidad **y** filtraria la
    conversacion de un usuario a la de otro. Es el error mas caro de esta
    arquitectura (RFC-0004 6), y solo se ve preguntando por lo contrario.
    """
    cliente = _cliente(database_url, guion=[*_guion_con_busqueda(), *_guion_con_busqueda()])
    cliente.post("/v1/chat", headers={"X-API-Key": _CLAVE}, json={"message": "Secreto del primero"})

    cliente.post("/v1/chat", headers={"X-API-Key": _CLAVE}, json={"message": "Conversacion nueva"})

    recibido = _texto_de_los_mensajes(cliente)
    assert "Secreto del primero" not in recibido, "una conversacion filtro en otra"


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
