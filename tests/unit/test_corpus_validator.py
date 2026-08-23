"""RFC-0002 CA-9: el validador rechaza un corpus con `###` y uno con un
telefono personal. A-5: tambien el front-matter incompleto (Mayor).

El corpus valido es un fixture sintetico (tests/unit/ingestion_fixtures.py),
nunca corpus/cv.md -- ese archivo no se versiona (RFC-0016 3.3) y no existe
en CI."""

import pytest

from app.ingestion.corpus_validator import CorpusValidationError, validate_corpus
from tests.unit.ingestion_fixtures import VALID_CORPUS

pytestmark = pytest.mark.unit


def test_valid_corpus_passes() -> None:
    validate_corpus(VALID_CORPUS)


def test_rejects_triple_hash() -> None:
    corpus = VALID_CORPUS.replace("## Empresa Uno", "### Empresa Uno subseccion\n## Empresa Uno")

    with pytest.raises(CorpusValidationError, match="###"):
        validate_corpus(corpus)


def test_rejects_personal_phone() -> None:
    corpus = VALID_CORPUS.replace(
        "Ingeniera de software con experiencia",
        "Tel: 55 1234 5678\nIngeniera de software con experiencia",
    )

    with pytest.raises(CorpusValidationError, match="sensible|telefono"):
        validate_corpus(corpus)


def test_rejects_missing_front_matter_key() -> None:
    corpus = VALID_CORPUS.replace('actualizado: "2026-08-22"\n', "")

    with pytest.raises(CorpusValidationError, match="actualizado"):
        validate_corpus(corpus)


def test_rejects_unit_over_400_words() -> None:
    long_bullet = " ".join(["palabra"] * 450)
    corpus = VALID_CORPUS.replace(
        "**Logros:**\n- Redujo el tiempo de ingesta en 40%.",
        f"**Logros:**\n- {long_bullet}",
    )

    with pytest.raises(CorpusValidationError, match="400"):
        validate_corpus(corpus)


def test_rejects_experience_unit_without_date_range() -> None:
    corpus = VALID_CORPUS.replace(
        "## Empresa Uno -- Ingeniera de Datos Senior            <!-- 2022-03 .. 2025-11 -->",
        "## Empresa Uno -- Ingeniera de Datos Senior",
    )

    with pytest.raises(CorpusValidationError, match="fecha"):
        validate_corpus(corpus)
