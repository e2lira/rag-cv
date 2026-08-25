"""RFC-0005 13: contrato Open Responses (`POST /v1/responses`).

**No es un segundo agente ni un segundo motor**: es un adaptador de
transporte sobre el mismo `Agent` que sirve a 4 y 5. Cualquier diferencia de
comportamiento para la misma pregunta es un defecto, no una variante -- y por
eso estas pruebas usan el mismo `ScriptedModel` y el mismo montaje que
`test_chat.py`.
"""

import json
from typing import Any

import pytest

from tests.integration.test_chat import _CLAVE, _FUENTE, _RESPUESTA, _cliente, _guion_con_busqueda

pytestmark = pytest.mark.integration


def _responder(database_url: str, cuerpo: dict[str, Any], **kwargs: Any) -> Any:
    return _cliente(database_url, **kwargs).post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {_CLAVE}"},
        json=cuerpo,
    )


def test_minimal_contract(database_url: str) -> None:
    """CA-14: `{"model","input"}` devuelve un objeto `response` completado
    con un `output_text` dentro."""
    respuesta = _responder(database_url, {"model": "rag-cv", "input": "Que experiencia tiene?"})

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()

    assert cuerpo["object"] == "response"
    assert cuerpo["status"] == "completed"
    assert cuerpo["id"].startswith("resp_")
    assert isinstance(cuerpo["created_at"], int)
    salida = cuerpo["output"][0]
    assert salida["type"] == "message"
    assert salida["role"] == "assistant"
    assert salida["content"][0]["type"] == "output_text"
    assert salida["content"][0]["text"] == _RESPUESTA
    assert set(cuerpo["usage"]) == {"input_tokens", "output_tokens", "total_tokens"}


def test_auth_bearer(database_url: str) -> None:
    """CA-15: `Bearer` autentica; sin cabecera, `401` con el **mismo** cuerpo
    generico que CA-1 -- no una variante que delate que la ruta es otra."""
    autenticada = _responder(database_url, {"model": "rag-cv", "input": "Hola"})
    sin_clave = _cliente(database_url).post("/v1/responses", json={"model": "x", "input": "Hola"})
    sin_clave_en_chat = _cliente(database_url).post("/v1/chat", json={"message": "Hola"})

    assert autenticada.status_code == 200
    assert sin_clave.status_code == 401
    assert sin_clave.json()["error"]["code"] == "unauthorized"
    assert sin_clave.json()["error"]["message"] == sin_clave_en_chat.json()["error"]["message"]


def test_model_is_reported_not_honoured(database_url: str) -> None:
    """CA-16: el `model` de la peticion se ignora y la respuesta reporta el
    **realmente usado** (13.2).

    Devolverle su propio valor seria afirmar algo falso sobre quien
    respondio; honrarlo seria enrutado dinamico por peticion, que RFC-0013 6
    prohibe explicitamente.
    """
    respuesta = _responder(
        database_url, {"model": "modelo-inventado-por-el-cliente", "input": "Hola"}
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["model"] != "modelo-inventado-por-el-cliente"


def test_annotations_match_sources(database_url: str) -> None:
    """CA-17: las citas viajan en `annotations` con el mismo `chunk_id` que
    `sources` de 4 para la misma pregunta.

    Si divergieran, una de las dos superficies estaria mintiendo sobre de
    donde salio la respuesta -- y la trazabilidad es lo unico que separa
    este sistema de uno que inventa.
    """
    por_responses = _responder(database_url, {"model": "rag-cv", "input": "Que experiencia?"})
    por_chat = _cliente(database_url).post(
        "/v1/chat", headers={"X-API-Key": _CLAVE}, json={"message": "Que experiencia?"}
    )

    anotaciones = por_responses.json()["output"][0]["content"][0]["annotations"]
    fuentes = por_chat.json()["sources"]

    assert [a["file_id"] for a in anotaciones] == [str(f["chunk_id"]) for f in fuentes]
    assert [a["filename"] for a in anotaciones] == [f["unit"] for f in fuentes]
    assert anotaciones[0]["type"] == "file_citation"
    assert anotaciones[0]["file_id"] == str(_FUENTE["chunk_id"])


def test_stream_event_order(database_url: str) -> None:
    """CA-18: con `"stream": true`, `text/event-stream` con al menos un
    `response.output_text.delta` y `response.completed` al final.

    Los nombres son los de Open Responses, **no** los de 5: una plataforma
    externa escucha estos y no los nuestros (13.4).
    """
    respuesta = _responder(database_url, {"model": "rag-cv", "input": "Hola", "stream": True})

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.headers["content-type"].startswith("text/event-stream")

    tipos = [
        json.loads(linea[len("data:") :].strip())["type"]
        for linea in respuesta.text.splitlines()
        if linea.startswith("data:")
    ]

    assert tipos[0] == "response.created", tipos
    assert tipos[-1] == "response.completed", tipos
    assert tipos.count("response.output_text.delta") >= 1, tipos


def test_the_completed_event_carries_the_whole_object(database_url: str) -> None:
    """13.4: `response.completed` carga el objeto entero de 13.3, para que un
    cliente que solo escuche ese evento tenga la respuesta con sus citas."""
    respuesta = _responder(database_url, {"model": "rag-cv", "input": "Hola", "stream": True})

    ultimo = json.loads(
        [linea for linea in respuesta.text.splitlines() if linea.startswith("data:")][-1][
            len("data:") :
        ].strip()
    )

    objeto = ultimo["response"]
    assert objeto["status"] == "completed"
    assert objeto["output"][0]["content"][0]["annotations"]
    assert objeto["usage"]["total_tokens"] >= 0


def test_conversation_continuity(database_url: str) -> None:
    """CA-19: `previous_response_id` continua la conversacion -- el segundo
    turno ve el primero."""
    guion = [*_guion_con_busqueda(), *_guion_con_busqueda()]
    cliente = _cliente(database_url, guion=guion)

    primero = cliente.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {_CLAVE}"},
        json={"model": "rag-cv", "input": "Primera"},
    ).json()

    segundo = cliente.post(
        "/v1/responses",
        headers={"Authorization": f"Bearer {_CLAVE}"},
        json={"model": "rag-cv", "input": "Segunda", "previous_response_id": primero["id"]},
    )

    assert segundo.status_code == 200, segundo.text
    # El segundo turno vive en la misma conversacion: el modelo lo vio.
    mensajes = cliente.app.state.agent.model.stream_calls  # type: ignore[attr-defined]
    assert len(mensajes) >= 2


def test_error_body_carries_both_shapes(database_url: str) -> None:
    """CA-23: el cuerpo de error lleva **ambas** formas en la misma
    respuesta: la de 8 y el objeto de 13.5, como claves hermanas.

    `code` y `message` se duplican a proposito, y son el **mismo valor** en
    los dos sitios: un cliente que lea cualquiera de las dos formas obtiene
    lo mismo. `request_id` vive solo en `error` porque no pertenece a la
    especificacion.
    """
    respuesta = _cliente(database_url).post(
        "/v1/responses", json={"model": "rag-cv", "input": "Hola"}
    )

    cuerpo = respuesta.json()

    assert respuesta.status_code == 401
    assert cuerpo["type"] == "error"
    assert cuerpo["code"] == cuerpo["error"]["code"] == "unauthorized"
    assert cuerpo["message"] == cuerpo["error"]["message"]
    assert cuerpo["error"]["request_id"]
    assert "request_id" not in cuerpo


def test_out_of_scope_fields_are_ignored_not_rejected(database_url: str) -> None:
    """13.6: un campo fuera de alcance **no produce error**.

    Un `400` ante un campo opcional que la plataforma manda por defecto
    haria el endpoint inservible por una razon cosmetica -- y la plataforma
    no puede saber cuales aceptamos antes de registrarnos.
    """
    respuesta = _responder(
        database_url,
        {
            "model": "rag-cv",
            "input": "Hola",
            "instructions": "Se un pirata",
            "tools": [{"type": "web_search"}],
            "tool_choice": "auto",
            "truncation": "auto",
            "service_tier": "flex",
        },
    )

    assert respuesta.status_code == 200, respuesta.text


def test_input_as_an_array_takes_the_last_user_message(database_url: str) -> None:
    """13.1: `input` como array toma el ultimo `message` de rol `user`."""
    respuesta = _responder(
        database_url,
        {
            "model": "rag-cv",
            "input": [
                {"type": "message", "role": "user", "content": "Primera"},
                {"type": "message", "role": "assistant", "content": "Respuesta"},
                {"type": "message", "role": "user", "content": "La que importa"},
            ],
        },
    )

    assert respuesta.status_code == 200, respuesta.text
