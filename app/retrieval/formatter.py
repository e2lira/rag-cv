"""Formateo del bloque citable devuelto al agente -- RFC-0003 4.1."""

from app.retrieval.hybrid import RetrievedChunk

_INSTRUCTION = (
    "Instrucción de uso: responde únicamente con la información contenida entre "
    "las etiquetas <contexto_cv>. Cita las referencias como [F1], [F2]. Si la "
    "respuesta no está ahí, dilo."
)


def _tag(chunk: RetrievedChunk, label: str) -> str:
    header = f"{chunk.section} > {chunk.unit}"
    if chunk.parts > 1:
        header = f"{header}, parte {chunk.part}/{chunk.parts}"
    return f"[{label} | {header}]"


def format_context_block(chunks: list[RetrievedChunk]) -> str:
    entries = [f"{_tag(chunk, f'F{i}')}\n{chunk.content}" for i, chunk in enumerate(chunks, 1)]
    body = "\n\n".join(entries)

    if not chunks:
        return "<contexto_cv>\n</contexto_cv>"

    return f"<contexto_cv>\n{body}\n</contexto_cv>\n\n{_INSTRUCTION}"
