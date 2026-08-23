"""Chunking del corpus -- RFC-0002 4, 5."""

import hashlib
import re
from dataclasses import dataclass
from datetime import date

from app.ingestion.corpus_parser import iter_units
from app.ingestion.synonyms import normalize_tech_tag

_DATE_COMMENT_RE = re.compile(
    r"<!--\s*(?P<sy>\d{4})-(?P<sm>\d{2})\s*\.\.\s*(?:(?P<ey>\d{4})-(?P<em>\d{2})|actual)\s*-->"
)
_STACK_LINE_RE = re.compile(r"^\*\*Stack:\*\*\s*(.+)$", re.MULTILINE)

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
        return f"{start_str} a la actualidad"
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
) -> str:
    # A-1: el mismo texto que se embebe se devuelve al agente -- por eso la
    # cabecera se antepone al content, no se maneja aparte.
    parts = [f"Sección: {section} > {unit}"]
    date_range = _format_date_range(date_start, date_end)
    if date_range is not None:
        parts.append(date_range)
    if tech_tags:
        parts.append(f"Stack: {', '.join(tech_tags)}")
    return f"[{' | '.join(parts)}]"


def chunk_corpus(text: str, *, doc_id: str = "cv") -> list[Chunk]:
    chunks: list[Chunk] = []
    for unit in iter_units(text):
        title = _clean_title(unit.raw_title)
        date_start, date_end = _parse_date_range(unit.raw_title)
        tech_tags = _extract_tech_tags(unit.body)
        header = _build_context_header(unit.section, title, date_start, date_end, tech_tags)
        content = f"{header}\n{unit.body.strip()}"
        chunks.append(
            Chunk(
                doc_id=doc_id,
                section=unit.section,
                unit=title,
                chunk_type=_SECTION_TO_CHUNK_TYPE.get(unit.section, "faq"),
                date_start=date_start,
                date_end=date_end,
                tech_tags=tech_tags,
                part=1,
                parts=1,
                content=content,
                content_hash=_content_hash(content),
                token_count=len(content.split()),
            )
        )
    return chunks
