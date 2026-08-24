"""RFC-0003 8, CA-10: p95 de hybrid_search sobre un corpus de 200 fragmentos.

Fixture DISTINTA de retrieval_fixtures.CORPUS (30, para las pruebas
funcionales) -- RFC-0003 8 las nombra por separado a proposito: esta solo
mide volumen, no necesita contenido realista."""

import hashlib
import time

import psycopg
import pytest

from app.retrieval.embedder_fake import FakeEmbedder
from app.retrieval.hybrid import hybrid_search

pytestmark = pytest.mark.integration

_PERF_CORPUS_SIZE = 200
_SAMPLES = 20
_P95_BUDGET_MS = 250


async def _seed_perf_corpus(conn: psycopg.Connection, embedder: FakeEmbedder) -> None:
    contents = [
        f"Fragmento sintetico numero {i} para medir latencia de recuperacion "
        f"hibrida sobre un corpus de tamano real, con texto variado sobre "
        f"tecnologia {i % 7} y proyecto {i % 11}."
        for i in range(_PERF_CORPUS_SIZE)
    ]
    vectors = await embedder.embed_documents(contents)

    with conn.cursor() as cur:
        for i, (content, vector) in enumerate(zip(contents, vectors, strict=True)):
            cur.execute(
                "INSERT INTO cv_chunks "
                "(doc_id, section, unit, chunk_type, part, parts, content, "
                " content_hash, token_count, tech_tags, embedding, embed_model_id) "
                "VALUES ('cv', 'Experiencia', %s, 'experiencia', 1, 1, %s, %s, %s, "
                " '{}', %s, %s)",
                (
                    f"Fragmento perf {i}",
                    content,
                    hashlib.sha256(content.encode()).hexdigest(),
                    len(content.split()),
                    "[" + ",".join(str(v) for v in vector) + "]",
                    embedder.model_id,
                ),
            )
    conn.commit()


@pytest.mark.asyncio
async def test_p95_latency_under_250ms(database_url: str) -> None:
    """CA-10: p95 de hybrid_search <= 250 ms sobre 200 fragmentos.

    Se miden 20 llamadas con consultas distintas (evita que el planificador
    cachee un plan para un unico literal) y se calcula el percentil 95 en
    Python, sin depender de ninguna libreria de estadistica."""
    embedder = FakeEmbedder(1536)
    with psycopg.connect(database_url) as conn:
        await _seed_perf_corpus(conn, embedder)

        durations_ms: list[float] = []
        for i in range(_SAMPLES):
            start = time.perf_counter()
            await hybrid_search(conn, embedder, f"tecnologia {i % 7} proyecto {i % 11}")
            durations_ms.append((time.perf_counter() - start) * 1000)

    durations_ms.sort()
    p95_index = int(len(durations_ms) * 0.95)
    p95 = durations_ms[min(p95_index, len(durations_ms) - 1)]

    assert p95 <= _P95_BUDGET_MS, f"p95 = {p95:.1f}ms, presupuesto {_P95_BUDGET_MS}ms"
