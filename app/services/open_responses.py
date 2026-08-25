"""Adaptador Open Responses -- RFC-0005 13 (RFC-0001 4: sin HTTP ni SQL).

**No es un segundo motor.** Traduce el turno que produce `app/services/chat.py`
al vocabulario de la especificacion, y nada mas. Si aqui hubiera una decision
de negocio propia, las dos superficies podrian responder distinto a la misma
pregunta -- que RFC-0005 13 declara defecto, no variante.
"""

from typing import Any

from app.services.chat import TurnResult

_PREFIJO = "resp_"


def response_id(message_id: str) -> str:
    """El identificador de la respuesta (13.3).

    Se construye sobre el `message_id` y no sobre la conversacion porque en
    la especificacion una *response* es una respuesta concreta: usar el id de
    la conversacion haria que dos turnos distintos compartieran identificador,
    y `previous_response_id` dejaria de poder senalar a cual continuar.
    """
    return f"{_PREFIJO}{message_id}"


def message_id_of(response_id_: str) -> str:
    """El `message_id` que hay dentro de un `previous_response_id` (13.1)."""
    return response_id_.removeprefix(_PREFIJO)


def extract_input(entrada: Any) -> str:
    """El mensaje del turno, venga como texto o como array de items (13.1).

    Del array se toma el **ultimo** `message` de rol `user`: los anteriores
    son historial que la plataforma reenvia, y responder al primero seria
    contestar una pregunta que el usuario ya dejo atras.
    """
    if isinstance(entrada, str):
        return entrada

    if isinstance(entrada, list):
        for item in reversed(entrada):
            if not isinstance(item, dict) or item.get("role") != "user":
                continue
            contenido = item.get("content")
            if isinstance(contenido, str):
                return contenido
            if isinstance(contenido, list):
                textos = [
                    str(parte.get("text", ""))
                    for parte in contenido
                    if isinstance(parte, dict) and parte.get("text")
                ]
                if textos:
                    return "".join(textos)

    # Ni texto ni un array con un mensaje de usuario: la capa API lo traduce
    # a 400 invalid_request (8). No se inventa un mensaje vacio, que gastaria
    # un turno del modelo en preguntar por nada.
    raise ValueError("input no trae ningun mensaje de rol user")


def annotations_from(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Las citas, en el unico campo del contrato donde caben (13.3).

    `file_id` lleva el `chunk_id` y `filename` la `unit`, y **tienen que**
    coincidir con `sources` de 4 para la misma pregunta (CA-17): si
    divergieran, una de las dos superficies estaria mintiendo sobre de donde
    salio la respuesta.
    """
    return [
        {
            "type": "file_citation",
            "index": indice,
            "file_id": str(fuente.get("chunk_id", "")),
            "filename": str(fuente.get("unit", "")),
        }
        for indice, fuente in enumerate(sources)
    ]


def response_object(turno: TurnResult, *, created_at: int) -> dict[str, Any]:
    """El objeto `response` de 13.3 a partir de un turno."""
    entrada = int(turno.usage.get("input_tokens", 0))
    salida = int(turno.usage.get("output_tokens", 0))
    return {
        "id": response_id(turno.message_id),
        "object": "response",
        "created_at": created_at,
        # `incomplete` si se agoto el limite de ejecucion de RFC-0004 8; hoy
        # el flujo no lo distingue de un turno normal, asi que se declara
        # completado solo cuando lo fue.
        "status": "completed",
        # El modelo REALMENTE usado, nunca el que pidio el cliente (13.2).
        "model": turno.meta.get("model_id"),
        "output": [
            {
                "id": f"msg_{turno.message_id}",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": turno.answer,
                        # Una abstencion es una respuesta completada normal
                        # con `annotations` vacio (13.3): el agente sabe
                        # decir "no consta", y eso no es un error.
                        "annotations": annotations_from(turno.sources),
                    }
                ],
            }
        ],
        # Sin `cost_usd`: no es parte del contrato Open Responses. Se sigue
        # registrando internamente y en /v1/chat (13.3).
        "usage": {
            "input_tokens": entrada,
            "output_tokens": salida,
            "total_tokens": entrada + salida,
        },
    }
