"""Recuperacion hibrida -- RFC-0003 3, 4.

HNSW + PostgreSQL FTS + fusion RRF, en una sola sentencia (A-4): ninguna
reindexacion concurrente puede intercalarse entre las dos ramas y la carga
final, porque las tres leen del mismo snapshot de una unica consulta. La
fusion (aritmetica sobre los rangos ya leidos) ocurre en Python via
app.retrieval.rrf.fuse_rrf, no en la sentencia: eso es lo que hace CA-3/CA-4
"RRF puro sin BD" verificable, sin reintroducir una segunda lectura -- los
rangos ya llegaron en el unico SELECT.
"""

from dataclasses import dataclass
from datetime import date

import psycopg
from psycopg import sql

from app.ingestion.query_expansion import expand_query_terms
from app.retrieval.embedder import Embedder
from app.retrieval.rrf import RankedCandidate, fuse_rrf

# Las dos ramas y la carga final, en UNA sentencia (A-4): un unico snapshot,
# ninguna reindexacion puede intercalarse entre "leo lo vectorial" y "leo lo
# lexico". La fusion NO se calcula aqui -- solo se devuelven los rangos, y
# fuse_rrf hace la aritmetica sobre filas ya leidas atomicamente.
_HYBRID_SQL = """
WITH semantic AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> %(qv)s::vector, id) AS rank
    FROM cv_chunks
    WHERE doc_id = %(doc_id)s
    ORDER BY embedding <=> %(qv)s::vector, id
    LIMIT %(candidates)s
),
lexical AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY ts_rank_cd(tsv, query) DESC, id) AS rank
    FROM cv_chunks, websearch_to_tsquery('public.es_unaccent', %(q)s) AS query
    WHERE doc_id = %(doc_id)s AND tsv @@ query
    ORDER BY ts_rank_cd(tsv, query) DESC, id
    LIMIT %(candidates)s
),
combined AS (
    SELECT COALESCE(s.id, l.id) AS id, s.rank AS sem_rank, l.rank AS lex_rank
    FROM semantic s FULL OUTER JOIN lexical l ON s.id = l.id
)
SELECT c.id, c.doc_id, c.section, c.unit, c.chunk_type, c.part, c.parts,
       c.content, c.date_start, c.date_end, c.tech_tags,
       combined.sem_rank, combined.lex_rank
FROM combined JOIN cv_chunks c ON c.id = combined.id
"""


@dataclass(frozen=True)
class RetrievedChunk:
    id: int
    doc_id: str
    section: str
    unit: str
    chunk_type: str
    part: int
    parts: int
    content: str
    date_start: date | None
    date_end: date | None
    tech_tags: tuple[str, ...]
    score: float
    sem_rank: int | None
    lex_rank: int | None


def _format_vector(vector: list[float]) -> str:
    return "[" + ",".join(str(v) for v in vector) + "]"


async def hybrid_search(
    conn: psycopg.Connection,
    embedder: Embedder,
    query: str,
    *,
    doc_id: str = "cv",
    top_k: int = 5,
    candidates: int = 20,
    ef_search: int = 40,
    rrf_k: int = 60,
    min_score: float = 0.016,
    w_sem: float = 1.0,
    w_lex: float = 1.0,
    timeout_ms: int = 2000,
) -> list[RetrievedChunk]:
    query_vector = await embedder.embed_query(query)
    lexical_query = expand_query_terms(query)

    with conn.cursor() as cur:
        # SET LOCAL no acepta parametros ligados (limitacion de PostgreSQL,
        # no de psycopg); sql.Literal compone el valor de forma segura sin
        # concatenar texto. No lee datos: A-4 no lo cuenta como sentencia.
        cur.execute(sql.SQL("SET LOCAL hnsw.ef_search = {}").format(sql.Literal(ef_search)))
        cur.execute(sql.SQL("SET LOCAL statement_timeout = {}").format(sql.Literal(timeout_ms)))

        cur.execute(
            _HYBRID_SQL,
            {
                "qv": _format_vector(query_vector),
                "q": lexical_query,
                "doc_id": doc_id,
                "candidates": candidates,
            },
        )
        rows = cur.fetchall()
        conn.rollback()

    _RowRest = tuple[str, str, str, str, int, int, str, date | None, date | None, list[str]]
    ranked: list[RankedCandidate] = []
    rows_by_id: dict[int, _RowRest] = {}
    for row in rows:
        cid = row[0]
        rows_by_id[cid] = row[1:11]
        ranked.append(RankedCandidate(id=cid, sem_rank=row[11], lex_rank=row[12]))

    fused = fuse_rrf(ranked, k=rrf_k, w_sem=w_sem, w_lex=w_lex)[:top_k]

    return [
        RetrievedChunk(
            id=f.id,
            doc_id=rows_by_id[f.id][0],
            section=rows_by_id[f.id][1],
            unit=rows_by_id[f.id][2],
            chunk_type=rows_by_id[f.id][3],
            part=rows_by_id[f.id][4],
            parts=rows_by_id[f.id][5],
            content=rows_by_id[f.id][6],
            date_start=rows_by_id[f.id][7],
            date_end=rows_by_id[f.id][8],
            tech_tags=tuple(rows_by_id[f.id][9]),
            score=f.score,
            sem_rank=f.sem_rank,
            lex_rank=f.lex_rank,
        )
        for f in fused
    ]
