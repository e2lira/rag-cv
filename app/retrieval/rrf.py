"""Fusion RRF -- RFC-0003 3.4.

Recibe los rangos de las dos ramas -- ya obtenidos por la sentencia unica
de hybrid_search (RFC-0003 A-4) -- y calcula el score fusionado en Python.
Pura y sin E/S: es lo que hace posible probar la formula "sin BD" (RFC-0003
8, CA-3/CA-4), separado del acceso a datos.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RankedCandidate:
    id: int
    sem_rank: int | None
    lex_rank: int | None


@dataclass(frozen=True)
class FusedResult:
    id: int
    score: float
    sem_rank: int | None
    lex_rank: int | None


def fuse_rrf(
    candidates: list[RankedCandidate],
    *,
    k: int = 60,
    w_sem: float = 1.0,
    w_lex: float = 1.0,
) -> list[FusedResult]:
    raise NotImplementedError
