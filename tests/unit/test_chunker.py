"""RFC-0002 CA-1/CA-2/CA-3/CA-4: chunking del corpus.

Cada criterio tiene una implementacion separable dentro de chunker.py --
revertir una no reenrojece a las otras (RFC-0014 6.1.1): va por criterio,
no en forma de suite completa."""

import pytest

from app.ingestion.chunker import chunk_corpus
from tests.unit.ingestion_fixtures import VALID_CORPUS

pytestmark = pytest.mark.unit


def test_one_unit_one_chunk() -> None:
    """CA-1: un ## bajo # Experiencia produce exactamente un fragmento si
    mide <=1200 caracteres."""
    chunks = chunk_corpus(VALID_CORPUS)

    matching = [c for c in chunks if c.unit == "Empresa Dos -- Desarrolladora Backend"]

    assert len(matching) == 1
    assert matching[0].part == 1
    assert matching[0].parts == 1
    assert matching[0].section == "Experiencia"
    assert matching[0].chunk_type == "experiencia"
