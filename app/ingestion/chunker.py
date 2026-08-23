"""Chunking del corpus -- RFC-0002 4, 5."""

import hashlib
from dataclasses import dataclass
from datetime import date

from app.ingestion.corpus_parser import iter_units

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


def chunk_corpus(text: str, *, doc_id: str = "cv") -> list[Chunk]:
    chunks: list[Chunk] = []
    for unit in iter_units(text):
        content = unit.body.strip()
        chunks.append(
            Chunk(
                doc_id=doc_id,
                section=unit.section,
                unit=_clean_title(unit.raw_title),
                chunk_type=_SECTION_TO_CHUNK_TYPE.get(unit.section, "faq"),
                date_start=None,
                date_end=None,
                tech_tags=(),
                part=1,
                parts=1,
                content=content,
                content_hash=_content_hash(content),
                token_count=len(content.split()),
            )
        )
    return chunks
