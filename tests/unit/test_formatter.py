"""RFC-0003 4.1: formato del bloque citable devuelto al agente.

Sin BD: RetrievedChunk se construye a mano con los campos que la funcion
necesita."""

from datetime import date

import pytest

from app.retrieval.formatter import format_context_block
from app.retrieval.hybrid import RetrievedChunk

pytestmark = pytest.mark.unit


def _chunk(**overrides: object) -> RetrievedChunk:
    base = {
        "id": 1,
        "doc_id": "cv",
        "section": "Experiencia",
        "unit": "Empresa Uno -- Ingeniera de Datos Senior",
        "chunk_type": "experiencia",
        "part": 1,
        "parts": 1,
        "content": "Contenido del fragmento.",
        "date_start": None,
        "date_end": None,
        "tech_tags": (),
        "score": 0.03,
        "sem_rank": 1,
        "lex_rank": None,
    }
    base.update(overrides)
    return RetrievedChunk(**base)  # type: ignore[arg-type]


def test_wraps_content_in_context_tags() -> None:
    """RFC-0003 4.1 / I-2: el contenido va delimitado como datos. La
    instruccion de uso va DESPUES del cierre, per el ejemplo de 4.1 -- el
    bloque no termina en la etiqueta de cierre cuando hay resultados."""
    block = format_context_block([_chunk()])

    assert block.startswith("<contexto_cv>")
    assert "</contexto_cv>" in block


def test_labels_are_local_and_sequential() -> None:
    """Los identificadores F1..Fn son locales a la llamada: empiezan en 1 y
    siguen el orden de la lista recibida, no el id real del fragmento."""
    chunks = [_chunk(id=99, unit="A"), _chunk(id=5, unit="B")]

    block = format_context_block(chunks)

    assert "[F1 | " in block
    assert "[F2 | " in block
    assert "F99" not in block
    assert "F5" not in block


def test_tag_includes_section_and_unit() -> None:
    block = format_context_block([_chunk(section="Proyectos", unit="Buscador semantico de CVs")])

    assert "[F1 | Proyectos > Buscador semantico de CVs]" in block


def test_tag_includes_part_only_when_split() -> None:
    """RFC-0003 4.1: la parte solo aparece si parts > 1."""
    single = format_context_block([_chunk(part=1, parts=1)])
    split = format_context_block([_chunk(part=2, parts=3)])

    assert ", parte" not in single
    assert "parte 2/3" in split


def test_each_chunk_content_appears_after_its_tag() -> None:
    chunks = [
        _chunk(id=1, unit="A", content="Contenido de A"),
        _chunk(id=2, unit="B", content="Contenido de B"),
    ]

    block = format_context_block(chunks)

    assert block.index("[F1 |") < block.index("Contenido de A") < block.index("[F2 |")
    assert "Contenido de B" in block


def test_includes_usage_instruction() -> None:
    block = format_context_block([_chunk()])

    assert "responde únicamente con la información contenida" in block
    assert "[F1]" in block.split("</contexto_cv>")[1]


def test_empty_list_produces_empty_tags_no_instruction() -> None:
    """Sin resultados (CA-6) el bloque no debe invitar a citar nada que no
    existe."""
    block = format_context_block([])

    assert "<contexto_cv>" in block
    assert "</contexto_cv>" in block
    assert "[F1" not in block


def test_tag_does_not_render_dates() -> None:
    """RFC-0003 4.1 solo usa section/unit/parte -- no fechas. Una fecha en
    la etiqueta seria confusa sin el contexto que RFC-0002 le da en la
    cabecera de ingesta."""
    block = format_context_block([_chunk(date_start=date(2022, 3, 1), date_end=date(2025, 11, 1))])

    assert "2022" not in block
    assert "2025" not in block
