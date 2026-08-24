"""RFC-0005 4, CA-22: `usage.cost_usd` a partir de los tokens del turno.

Las pruebas inyectan su propia tabla de precios. No es comodidad: las
cifras reales las publica el proveedor y cambian, y una prueba anclada a
ellas se pondria roja el dia que suban un precio -- por una razon que no
tiene nada que ver con nuestro codigo. Lo que CA-22 exige verificar es la
**aritmetica** y el trato del modelo desconocido.
"""

import pytest

from app.core.pricing import ModelPrice, cost_usd

pytestmark = pytest.mark.unit

_TABLA = {"modelo-de-prueba": ModelPrice(input_per_million=1.0, output_per_million=5.0)}


def test_cost_from_token_counts() -> None:
    """CA-22: entrada y salida se cobran a tarifas distintas."""
    coste = cost_usd(
        "modelo-de-prueba", input_tokens=1_000_000, output_tokens=1_000_000, prices=_TABLA
    )

    assert coste == pytest.approx(6.0)


def test_partial_millions_are_prorated() -> None:
    """2 000 de entrada a 1 USD/millon = 0.002; 500 de salida a 5 = 0.0025."""
    coste = cost_usd("modelo-de-prueba", input_tokens=2_000, output_tokens=500, prices=_TABLA)

    assert coste == pytest.approx(0.0045)


def test_unknown_model_is_null() -> None:
    """CA-22, la parte que importa: un modelo sin precio da `None`, **nunca
    `0.0`**. Cero afirma que el turno fue gratis y contaminaria la metrica
    de coste de RFC-0009 4 sin que nada fallara."""
    assert cost_usd("modelo-que-no-esta", input_tokens=100, output_tokens=50, prices=_TABLA) is None


def test_a_zero_token_turn_costs_zero_not_null() -> None:
    """Aqui `0.0` si es la verdad: el modelo tiene precio y no se gastaron
    tokens. Distinguirlo de `None` es lo que hace util al campo."""
    coste = cost_usd("modelo-de-prueba", input_tokens=0, output_tokens=0, prices=_TABLA)

    assert coste == 0.0
    assert coste is not None


def test_the_production_table_uses_dated_model_ids() -> None:
    """ADR-0012: el precio se ancla a la version con fecha, no al alias. Si
    el proveedor mueve el modelo detras del alias, el precio dejaria de
    corresponder al modelo que respondio y nada fallaria."""
    from app.core.pricing import PRICES

    for model_id in PRICES:
        assert any(c.isdigit() for c in model_id.split("-")[-1]), (
            f"{model_id!r} parece un alias, no una version con fecha (ADR-0012)"
        )
