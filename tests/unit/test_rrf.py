"""RFC-0003 3.4: fusion RRF pura, sin BD -- rangos sinteticos.

Formaliza el algoritmo con el mismo aislamiento con el que test_chunker.py
(RFC-0002) prueba el troceado: sin abrir una conexion, sobre entradas
fabricadas."""

import pytest

from app.retrieval.rrf import FusedResult, RankedCandidate, fuse_rrf

pytestmark = pytest.mark.unit


def test_single_branch_identity() -> None:
    """CA-3: con una sola rama activa (lex_rank siempre None), la fusion
    produce el mismo orden que esa rama -- el score es monotono decreciente
    en sem_rank, y por tanto el orden coincide exacto con la rama semantica."""
    candidates = [
        RankedCandidate(id=30, sem_rank=3, lex_rank=None),
        RankedCandidate(id=10, sem_rank=1, lex_rank=None),
        RankedCandidate(id=20, sem_rank=2, lex_rank=None),
    ]

    fused = fuse_rrf(candidates, k=60, w_sem=1.0, w_lex=1.0)

    assert [r.id for r in fused] == [10, 20, 30]


def test_single_branch_identity_lexical() -> None:
    """Lo mismo con la rama lexica sola: solo debe importar lex_rank."""
    candidates = [
        RankedCandidate(id=1, sem_rank=None, lex_rank=5),
        RankedCandidate(id=2, sem_rank=None, lex_rank=1),
        RankedCandidate(id=3, sem_rank=None, lex_rank=3),
    ]

    fused = fuse_rrf(candidates, k=60, w_sem=1.0, w_lex=1.0)

    assert [r.id for r in fused] == [2, 3, 1]


def test_both_branches_agree_reinforces_score() -> None:
    """Un id que aparece en las dos ramas debe superar a uno que solo
    aparece en una, aun con rangos peores en cada rama individual -- es la
    propiedad que justifica RRF sobre elegir la mejor rama."""
    candidates = [
        RankedCandidate(id=1, sem_rank=5, lex_rank=5),
        RankedCandidate(id=2, sem_rank=1, lex_rank=None),
    ]

    fused = fuse_rrf(candidates, k=60, w_sem=1.0, w_lex=1.0)

    assert fused[0].id == 1


def test_score_formula_matches_rrf_k60() -> None:
    """El score exacto para k=60, pesos 1.0: 1/(60+sem)+1/(60+lex)."""
    candidates = [RankedCandidate(id=1, sem_rank=2, lex_rank=4)]

    fused = fuse_rrf(candidates, k=60, w_sem=1.0, w_lex=1.0)

    expected = 1.0 / (60 + 2) + 1.0 / (60 + 4)
    assert fused[0].score == pytest.approx(expected)


def test_weights_scale_each_branch_independently() -> None:
    """RFC-0003 3.4: los pesos son la palanca de ajuste ante sesgo hacia una
    rama -- deben escalar la contribucion de cada rama por separado."""
    candidates = [RankedCandidate(id=1, sem_rank=1, lex_rank=1)]

    fused = fuse_rrf(candidates, k=60, w_sem=2.0, w_lex=0.5)

    expected = 2.0 / 61 + 0.5 / 61
    assert fused[0].score == pytest.approx(expected)


def test_returns_fused_result_with_original_ranks() -> None:
    """El resultado conserva sem_rank y lex_rank originales -- RFC-0005
    los expone en la respuesta para trazabilidad."""
    candidates = [RankedCandidate(id=1, sem_rank=3, lex_rank=7)]

    fused = fuse_rrf(candidates, k=60, w_sem=1.0, w_lex=1.0)

    assert fused[0] == FusedResult(
        id=1, score=pytest.approx(1 / 63 + 1 / 67), sem_rank=3, lex_rank=7
    )
