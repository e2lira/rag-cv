"""Chunking del corpus -- RFC-0002 4, 5."""

import hashlib
import re
from dataclasses import dataclass
from datetime import date

from app.ingestion.corpus_parser import iter_sections_without_units, iter_units, parse_front_matter
from app.ingestion.synonyms import normalize_tech_tag

_DATE_COMMENT_RE = re.compile(
    r"<!--\s*(?P<sy>\d{4})-(?P<sm>\d{2})\s*\.\.\s*(?:(?P<ey>\d{4})-(?P<em>\d{2})|actual)\s*-->"
)
_STACK_LINE_RE = re.compile(r"^\*\*Stack:\*\*\s*(.+)$", re.MULTILINE)

# RFC-0002 4.2: >1200 caracteres tras el enriquecimiento -> sub-fragmentos de
# ~800 con solapamiento de 120, solo dentro de la unidad.
_SPLIT_THRESHOLD = 1200
_SPLIT_TARGET_LEN = 800
_SPLIT_OVERLAP = 120

_SECTION_TO_CHUNK_TYPE = {
    "Experiencia": "experiencia",
    "Proyectos": "proyecto",
    "Habilidades": "habilidad",
    "Educación y certificaciones": "educacion",
    "Educacion y certificaciones": "educacion",
    "Preguntas frecuentes": "faq",
    "Perfil": "perfil",
}


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    section: str
    unit: str
    chunk_type: str
    date_start: date | None
    date_end: date | None
    tech_tags: tuple[str, ...]
    part: int
    parts: int
    content: str
    content_hash: str
    token_count: int


def _clean_title(raw_title: str) -> str:
    return raw_title.split("<!--")[0].strip()


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _parse_date_range(raw_title: str) -> tuple[date | None, date | None]:
    match = _DATE_COMMENT_RE.search(raw_title)
    if match is None:
        return None, None
    start = date(int(match["sy"]), int(match["sm"]), 1)
    if match["ey"] is None:
        return start, None
    return start, date(int(match["ey"]), int(match["em"]), 1)


def _format_date_range(date_start: date | None, date_end: date | None) -> str | None:
    if date_start is None:
        return None
    start_str = f"{date_start:%Y-%m}"
    if date_end is None:
        return start_str  # regresion deliberada, ver RFC-0002 CA-2
    return f"{start_str} a {date_end:%Y-%m}"


def _extract_tech_tags(body: str) -> tuple[str, ...]:
    match = _STACK_LINE_RE.search(body)
    if match is None:
        return ()
    raw_tags = (tag.strip() for tag in match.group(1).split(","))
    return tuple(normalize_tech_tag(tag) for tag in raw_tags if tag)


def _build_context_header(
    section: str,
    unit: str,
    date_start: date | None,
    date_end: date | None,
    tech_tags: tuple[str, ...],
    *,
    part: int,
    parts: int,
) -> str:
    # A-1: el mismo texto que se embebe se devuelve al agente -- por eso la
    # cabecera se antepone al content, no se maneja aparte.
    segments = [f"Sección: {section} > {unit}"]
    date_range = _format_date_range(date_start, date_end)
    if date_range is not None:
        segments.append(date_range)
    if tech_tags:
        segments.append(f"Stack: {', '.join(tech_tags)}")
    if parts > 1:
        segments.append(f"parte {part}/{parts}")
    return f"[{' | '.join(segments)}]"


def _split_body(body: str) -> list[str]:
    """RFC-0002 4.2: sub-fragmentos de ~800 caracteres con solapamiento de
    120, solo si la unidad supera el umbral de enriquecimiento."""
    if len(body) <= _SPLIT_TARGET_LEN:
        return [body]

    step = _SPLIT_TARGET_LEN - _SPLIT_OVERLAP
    pieces: list[str] = []
    start = 0
    while start < len(body):
        end = min(start + _SPLIT_TARGET_LEN, len(body))
        pieces.append(body[start:end])
        if end == len(body):
            break
        start += step
    return pieces


def _build_perfil_global(text: str, *, doc_id: str) -> Chunk:
    """RFC-0002 4.3: concatena front-matter, Perfil y los titulares de toda
    la experiencia (empresa, puesto, fechas, stack). unit='perfil_global',
    chunk_type='perfil' -- el DDL no admite 'perfil_global' como chunk_type."""
    front_matter = parse_front_matter(text)
    persona = str(front_matter.get("persona", ""))
    titular = str(front_matter.get("titular", ""))

    perfil_body = ""
    for section in iter_sections_without_units(text):
        if section.section == "Perfil":
            perfil_body = section.body
            break

    lines = [line for line in (f"{persona} -- {titular}".strip(" -"), perfil_body) if line]

    for unit in iter_units(text):
        if unit.section != "Experiencia":
            continue
        title = _clean_title(unit.raw_title)
        date_start, date_end = _parse_date_range(unit.raw_title)
        tags = _extract_tech_tags(unit.body)
        date_range = _format_date_range(date_start, date_end)
        headline = title if date_range is None else f"{title} ({date_range})"
        if tags:
            headline = f"{headline} -- Stack: {', '.join(tags)}"
        lines.append(headline)

    header = "[Sección: Perfil > perfil_global]"
    content = f"{header}\n" + "\n".join(lines)
    return Chunk(
        doc_id=doc_id,
        section="Perfil",
        unit="perfil_global",
        chunk_type="perfil",
        date_start=None,
        date_end=None,
        tech_tags=(),
        part=1,
        parts=1,
        content=content,
        content_hash=_content_hash(content),
        token_count=len(content.split()),
    )


def chunk_corpus(text: str, *, doc_id: str = "cv") -> list[Chunk]:
    chunks: list[Chunk] = []
    for unit in iter_units(text):
        title = _clean_title(unit.raw_title)
        date_start, date_end = _parse_date_range(unit.raw_title)
        tech_tags = _extract_tech_tags(unit.body)
        body = unit.body.strip()

        header_probe = _build_context_header(
            unit.section, title, date_start, date_end, tech_tags, part=1, parts=1
        )
        needs_split = len(header_probe) + 1 + len(body) > _SPLIT_THRESHOLD
        body_pieces = _split_body(body) if needs_split else [body]
        parts_total = len(body_pieces)

        for idx, piece in enumerate(body_pieces, start=1):
            header = _build_context_header(
                unit.section,
                title,
                date_start,
                date_end,
                tech_tags,
                part=idx,
                parts=parts_total,
            )
            content = f"{header}\n{piece}"
            chunks.append(
                Chunk(
                    doc_id=doc_id,
                    section=unit.section,
                    unit=title,
                    chunk_type=_SECTION_TO_CHUNK_TYPE.get(unit.section, "faq"),
                    date_start=date_start,
                    date_end=date_end,
                    tech_tags=tech_tags,
                    part=idx,
                    parts=parts_total,
                    content=content,
                    content_hash=_content_hash(content),
                    token_count=len(content.split()),
                )
            )
    chunks.append(_build_perfil_global(text, doc_id=doc_id))
    return chunks
