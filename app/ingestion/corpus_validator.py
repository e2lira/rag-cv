"""Validador del corpus -- RFC-0002 3.

Reglas del corpus (validadas aqui, fallan la ingesta si se incumplen):
  1. Front-matter YAML obligatorio con persona, titular y actualizado.
  2. Solo encabezados # y ##. ### esta prohibido.
  3. Cada ## bajo # Experiencia incluye el rango de fechas en un comentario
     HTML <!-- AAAA-MM .. AAAA-MM --> o el literal actual.
  4. Ninguna unidad ## supera las 400 palabras.
  5. Datos sensibles (documento de identidad, telefono personal, email
     personal) prohibidos.
"""

import re

from app.ingestion.corpus_parser import iter_units, parse_front_matter

_REQUIRED_FRONT_MATTER_KEYS = ("persona", "titular", "actualizado")

_FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_DATE_RANGE_RE = re.compile(r"<!--\s*\d{4}-\d{2}\s*\.\.\s*(?:\d{4}-\d{2}|actual)\s*-->")

# Formato CURP (18 caracteres) y RFC persona (13) mexicanos -- los unicos con
# estructura fija que un patron puede detectar de forma fiable. "Domicilio"
# de la regla 5 no tiene formato fijo y no se valida por patron.
_CURP_RE = re.compile(r"\b[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d\b")
_RFC_PERSONA_RE = re.compile(r"\b[A-ZÑ&]{4}\d{6}[A-Z0-9]{3}\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?52[\s.-]?)?\d{2}[\s.-]?\d{4}[\s.-]?\d{4}(?!\d)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


class CorpusValidationError(ValueError):
    """El corpus incumple una regla obligatoria -- RFC-0002 3."""


def validate_corpus(text: str) -> None:
    _validate_front_matter(text)
    _validate_no_triple_hash(text)
    _validate_experience_date_ranges(text)
    _validate_unit_word_counts(text)
    _validate_no_sensitive_data(text)


def _validate_front_matter(text: str) -> None:
    if _FRONT_MATTER_RE.match(text) is None:
        raise CorpusValidationError("falta el front-matter YAML obligatorio (RFC-0002 3 regla 1)")

    data = parse_front_matter(text)
    missing = [key for key in _REQUIRED_FRONT_MATTER_KEYS if key not in data]
    if missing:
        raise CorpusValidationError(
            f"al front-matter le falta: {', '.join(missing)} (RFC-0002 3 regla 1)"
        )


def _validate_no_triple_hash(text: str) -> None:
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.startswith("###"):
            raise CorpusValidationError(
                f"linea {lineno}: encabezado ### prohibido -- usa una unidad ## nueva "
                "(RFC-0002 3 regla 2)"
            )


def _validate_experience_date_ranges(text: str) -> None:
    for unit in iter_units(text):
        if unit.section != "Experiencia":
            continue
        if not _DATE_RANGE_RE.search(unit.raw_title):
            raise CorpusValidationError(
                f"la unidad {unit.raw_title.split('<!--')[0].strip()!r} bajo Experiencia no trae "
                "rango de fecha <!-- AAAA-MM .. AAAA-MM o actual --> (RFC-0002 3 regla 3)"
            )


def _validate_unit_word_counts(text: str) -> None:
    for unit in iter_units(text):
        word_count = len(unit.body.split())
        if word_count > 400:
            clean_title = unit.raw_title.split("<!--")[0].strip()
            raise CorpusValidationError(
                f"la unidad {clean_title!r} tiene {word_count} palabras, supera las 400 "
                "(RFC-0002 3 regla 4)"
            )


def _validate_no_sensitive_data(text: str) -> None:
    for pattern, label in (
        (_CURP_RE, "CURP"),
        (_RFC_PERSONA_RE, "RFC"),
        (_PHONE_RE, "telefono personal"),
        (_EMAIL_RE, "email personal"),
    ):
        if pattern.search(text):
            raise CorpusValidationError(f"dato sensible detectado ({label}) -- RFC-0002 3 regla 5")
