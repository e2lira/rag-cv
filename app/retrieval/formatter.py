"""Formateo del bloque citable devuelto al agente -- RFC-0003 4.1."""

from app.retrieval.hybrid import RetrievedChunk


def format_context_block(chunks: list[RetrievedChunk]) -> str:
    raise NotImplementedError
