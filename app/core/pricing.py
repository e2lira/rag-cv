"""Coste de un turno a partir de sus tokens -- RFC-0005 4.

Un `model_id` sin precio devuelve `None`, **nunca `0.0`**: cero afirma que
el turno fue gratis, y `None` dice la verdad -- que no se sabe -- sin
romper el esquema de la respuesta.

Los precios se fijan por **version con fecha**, no por alias (ADR-0012): si
el proveedor mueve el modelo detras del alias, el precio deja de
corresponder al modelo que respondio y nada falla.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    """Precio por millon de tokens, en USD."""

    input_per_million: float
    output_per_million: float


# Precios publicados por proveedor, por identificador con fecha.
PRICES: dict[str, ModelPrice] = {}


def cost_usd(
    model_id: str,
    *,
    input_tokens: int,
    output_tokens: int,
    prices: dict[str, ModelPrice] | None = None,
) -> float | None:
    """Coste del turno, o `None` si el modelo no tiene precio (RFC-0005 4)."""
    raise NotImplementedError  # RFC-0005 4: pendiente de su propio ciclo
