"""RFC-0002 CA-1/CA-2/CA-3/CA-4: chunking del corpus.

Cada criterio tiene una implementacion separable dentro de chunker.py --
revertir una no reenrojece a las otras (RFC-0014 6.1.1): va por criterio,
no en forma de suite completa."""

from datetime import date

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


def test_context_header() -> None:
    """CA-2: la cabecera de contexto contiene seccion, unidad y fechas
    cuando existen, en el texto que se embebe y se devuelve al agente
    (A-1: es el mismo texto)."""
    chunks = chunk_corpus(VALID_CORPUS)

    empresa_uno = next(c for c in chunks if c.unit == "Empresa Uno -- Ingeniera de Datos Senior")

    assert "Sección: Experiencia > Empresa Uno -- Ingeniera de Datos Senior" in empresa_uno.content
    assert "2022-03 a 2025-11" in empresa_uno.content
    assert empresa_uno.date_start == date(2022, 3, 1)
    assert empresa_uno.date_end == date(2025, 11, 1)
    assert "python" in empresa_uno.tech_tags
    assert "postgresql" in empresa_uno.tech_tags


def test_context_header_omits_dates_when_absent() -> None:
    """CA-2: "cuando existen" -- una unidad sin fechas (fuera de
    Experiencia) no inventa un rango."""
    chunks = chunk_corpus(VALID_CORPUS)

    proyecto = next(c for c in chunks if c.unit == "Buscador semantico de CVs")

    assert proyecto.date_start is None
    assert proyecto.date_end is None
    assert "Sección: Proyectos > Buscador semantico de CVs" in proyecto.content
