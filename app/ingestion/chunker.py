"""Chunking del corpus -- RFC-0002 4, 5."""

from dataclasses import dataclass
from datetime import date


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


def chunk_corpus(text: str, *, doc_id: str = "cv") -> list[Chunk]:
    raise NotImplementedError
