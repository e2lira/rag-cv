"""Corpus sintetico compartido por las pruebas de recuperacion hibrida --
RFC-0003. 8 fragmentos, por debajo de RETRIEVAL_CANDIDATES (20): asegura
que todo fragmento tenga rango semantico finito (nunca NULL), condicion
necesaria para que CA-1 sea determinista con FakeEmbedder (ver
_SemanticProxyEmbedder mas abajo, en test_retrieval.py)."""

import hashlib

import psycopg

CORPUS: list[tuple[str, str, str, str]] = [
    (
        "Experiencia",
        "Banorte -- Ingeniera de Datos Senior",
        "experiencia",
        "Trabajo en Banorte como ingeniera de datos senior, construyendo "
        "pipelines de ingesta para el area de riesgos.",
    ),
    (
        "Experiencia",
        "Comercio Digital SA -- Desarrolladora Backend",
        "experiencia",
        "Desarrollo APIs de catalogo y pagos en una plataforma de comercio "
        "electronico, usando Java y Spring.",
    ),
    (
        "Experiencia",
        "Coordinacion de equipo de datos",
        "experiencia",
        "Fue responsable de un equipo de 6 personas, coordinando entregas "
        "semanales del area de datos.",
    ),
    (
        "Proyectos",
        "Buscador semantico de CVs",
        "proyecto",
        "Diseno un buscador de candidatos con embeddings y PostgreSQL con "
        "pgvector, reduciendo el tiempo de filtrado manual.",
    ),
    (
        "Habilidades",
        "Lenguajes y frameworks",
        "habilidad",
        "Python, TypeScript, FastAPI, React.",
    ),
    (
        "Habilidades",
        "Cloud e infraestructura",
        "habilidad",
        "AWS, Docker, Terraform.",
    ),
    (
        "Educacion y certificaciones",
        "Ingenieria en Sistemas",
        "educacion",
        "Titulo profesional obtenido en 2019.",
    ),
    (
        "Preguntas frecuentes",
        "Disponibilidad",
        "faq",
        "Disponible para reubicacion dentro de Mexico.",
    ),
]


async def seed_corpus(conn: psycopg.Connection, embedder: object, *, doc_id: str = "cv") -> None:
    contents = [c[3] for c in CORPUS]
    vectors = await embedder.embed_documents(contents)  # type: ignore[attr-defined]

    with conn.cursor() as cur:
        for (section, unit, chunk_type, content), vector in zip(CORPUS, vectors, strict=True):
            cur.execute(
                "INSERT INTO cv_chunks "
                "(doc_id, section, unit, chunk_type, part, parts, content, "
                " content_hash, token_count, tech_tags, embedding, embed_model_id) "
                "VALUES (%s, %s, %s, %s, 1, 1, %s, %s, %s, %s, %s, %s)",
                (
                    doc_id,
                    section,
                    unit,
                    chunk_type,
                    content,
                    hashlib.sha256(content.encode()).hexdigest(),
                    len(content.split()),
                    [],
                    "[" + ",".join(str(v) for v in vector) + "]",
                    embedder.model_id,  # type: ignore[attr-defined]
                ),
            )
    conn.commit()
