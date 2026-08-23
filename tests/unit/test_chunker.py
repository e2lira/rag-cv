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


def test_context_header_ongoing_role_says_actualidad() -> None:
    """CA-2 / RFC-0002 3 regla 3: el literal "actual" en el comentario de
    fecha da date_end=None y la cabecera dice "a la actualidad", no una
    fecha inventada."""
    corpus = VALID_CORPUS.replace(
        "<!-- 2022-03 .. 2025-11 -->",
        "<!-- 2022-03 .. actual -->",
    )

    chunks = chunk_corpus(corpus)
    empresa_uno = next(c for c in chunks if c.unit == "Empresa Uno -- Ingeniera de Datos Senior")

    assert empresa_uno.date_start == date(2022, 3, 1)
    assert empresa_uno.date_end is None
    assert "2022-03 a la actualidad" in empresa_uno.content


def test_long_unit_split() -> None:
    """CA-3: una unidad de ~3000 caracteres produce sub-fragmentos con
    solapamiento de 120 y cabecera repetida en cada uno."""
    long_paragraph = "Detalle relevante del logro numero uno con contexto adicional. " * 50
    corpus = VALID_CORPUS.replace(
        "**Logros:**\n- Redujo el tiempo de ingesta en 40%.",
        f"**Logros:**\n- {long_paragraph}",
    )

    chunks = chunk_corpus(corpus)
    matching = sorted(
        (c for c in chunks if c.unit == "Empresa Uno -- Ingeniera de Datos Senior"),
        key=lambda c: c.part,
    )

    assert len(matching) > 1
    assert [c.parts for c in matching] == [len(matching)] * len(matching)
    assert [c.part for c in matching] == list(range(1, len(matching) + 1))

    for c in matching:
        assert "Sección: Experiencia > Empresa Uno -- Ingeniera de Datos Senior" in c.content

    for prev, nxt in zip(matching, matching[1:]):
        prev_body = prev.content.split("\n", 1)[1]
        next_body = nxt.content.split("\n", 1)[1]
        assert prev_body[-120:] == next_body[:120]


def test_global_summary_present() -> None:
    """CA-4: existe siempre un fragmento perfil_global -- unit='perfil_global',
    chunk_type='perfil' (RFC-0002 4.3: perfil_global es la unit, no el
    chunk_type, que el DDL restringe a un enum fijo)."""
    chunks = chunk_corpus(VALID_CORPUS)

    matching = [c for c in chunks if c.unit == "perfil_global"]

    assert len(matching) == 1
    global_chunk = matching[0]
    assert global_chunk.chunk_type == "perfil"
    assert global_chunk.part == 1
    assert global_chunk.parts == 1
    assert "Ana Prueba" in global_chunk.content
    assert "Empresa Uno" in global_chunk.content
    assert "Empresa Dos" in global_chunk.content


def test_context_header_omits_dates_when_absent() -> None:
    """CA-2: "cuando existen" -- una unidad sin fechas (fuera de
    Experiencia) no inventa un rango."""
    chunks = chunk_corpus(VALID_CORPUS)

    proyecto = next(c for c in chunks if c.unit == "Buscador semantico de CVs")

    assert proyecto.date_start is None
    assert proyecto.date_end is None
    assert "Sección: Proyectos > Buscador semantico de CVs" in proyecto.content
