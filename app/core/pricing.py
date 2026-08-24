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
    tarifa = (PRICES if prices is None else prices).get(model_id)
    if tarifa is None:
        # None y no 0.0: cero afirmaria que el turno fue gratis, y esa
        # mentira contaminaria la metrica de coste de RFC-0009 4 sin que
        # nada fallara.
        return None

    return (
        input_tokens * tarifa.input_per_million + output_tokens * tarifa.output_per_million
    ) / 1_000_000
