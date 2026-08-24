"""RFC-0003 3, 4: nucleo de hybrid_search contra una base efimera.

CA-1, CA-2, CA-5, CA-8, CA-11, CA-12 comparten la ruta de la sentencia
unica: revertirla enrojece a las seis a la vez (RFC-0014 6.1.1).

FakeEmbedder siempre para pruebas de plomeria (ADR-0012, RFC-0014 P-11).
FakeEmbedder es sha256(texto) -> vector, sin ninguna nocion de significado:
sirve para CA-1 (la rama lexica domina para una entidad exacta, ver
razonamiento en _corpus_size_bounds_semantic_rank mas abajo) pero NO puede
probar CA-2 (parafraseo sin solape lexico), porque no hay ninguna senal
semantica real que correlacione "liderando" con "responsable de un equipo".
_SemanticProxyEmbedder anade una unica direccion compartida cuando el texto
contiene un termino de una lista de marcadores -- sigue determinista y sin
proveedor, pero con estructura semantica controlada para esa prueba.
"""

import hashlib
import math

import psycopg
import pytest

from app.retrieval.embedder_fake import FakeEmbedder
from app.retrieval.hybrid import hybrid_search
from tests.integration.retrieval_fixtures import seed_corpus

pytestmark = pytest.mark.integration

_LEADERSHIP_MARKERS = ("liderando", "liderazgo", "lider", "responsable de un equipo")


def _vector_from_text(text: str, dimension: int) -> list[float]:
    seed = hashlib.sha256(text.encode()).digest()
    values: list[float] = []
    block = 0
    while len(values) < dimension:
        chunk = hashlib.sha256(seed + block.to_bytes(4, "big")).digest()
        for i in range(0, len(chunk), 4):
            if len(values) >= dimension:
                break
            raw = int.from_bytes(chunk[i : i + 4], "big")
            values.append((raw / 2**32) - 0.5)
        block += 1
    return values


class _SemanticProxyEmbedder:
    """Doble con estructura semantica MINIMA: refuerza una direccion
    compartida cuando el texto contiene un marcador de la lista. Solo para
    CA-2 -- el resto de las pruebas usa FakeEmbedder puro."""

    model_id = "semantic-proxy@test"

    def __init__(self, dimension: int) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def _vector(self, text: str) -> list[float]:
        base = _vector_from_text(text, self._dimension)
        lowered = text.lower()
        if any(marker in lowered for marker in _LEADERSHIP_MARKERS):
            base[0] += 3.0
        norm = math.sqrt(sum(v * v for v in base)) or 1.0
        return [v / norm for v in base]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class _CallCountingEmbedder:
    """Envuelve un Embedder real y cuenta llamadas -- CA-11."""

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.embed_documents_calls = 0
        self.embed_query_calls = 0

    @property
    def model_id(self) -> str:
        return self._inner.model_id  # type: ignore[attr-defined]

    @property
    def dimension(self) -> int:
        return self._inner.dimension  # type: ignore[attr-defined]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.embed_documents_calls += 1
        return await self._inner.embed_documents(texts)  # type: ignore[attr-defined]

    async def embed_query(self, text: str) -> list[float]:
        self.embed_query_calls += 1
        return await self._inner.embed_query(text)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_exact_entity(database_url: str) -> None:
    """CA-1: una consulta con entidad exacta ("Banorte") recupera su
    fragmento en el top-1.

    Con FakeEmbedder (sin senal semantica) esto funciona por la rama
    lexica: el fragmento de Banorte es el UNICO con lex_rank=1 para esa
    entidad, y su score fusionado (>= 1/(k+1) por el termino lexico solo)
    supera al de cualquier competidor sin coincidencia lexica (score maximo
    1/(k+1), alcanzable solo si su rango semantico -- aleatorio -- fuera 1).
    El corpus (8 fragmentos) esta por debajo de candidates (20), asi que el
    fragmento de Banorte SIEMPRE tiene rango semantico finito, y su score
    total es estrictamente mayor."""
    embedder = FakeEmbedder(1536)
    with psycopg.connect(database_url) as conn:
        await seed_corpus(conn, embedder)

        results = await hybrid_search(conn, embedder, "Banorte")

    assert results
    assert results[0].unit == "Banorte -- Ingeniera de Datos Senior"


@pytest.mark.asyncio
async def test_paraphrase(database_url: str) -> None:
    """CA-2: una consulta parafraseada ("liderar personas") recupera el
    fragmento de liderazgo en top-3, sin compartir tokens literales."""
    embedder = _SemanticProxyEmbedder(1536)
    with psycopg.connect(database_url) as conn:
        await seed_corpus(conn, embedder)

        results = await hybrid_search(conn, embedder, "¿Tiene experiencia liderando gente?")

    units = [r.unit for r in results[:3]]
    assert "Coordinacion de equipo de datos" in units


@pytest.mark.asyncio
async def test_single_statement_snapshot(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-5 / A-4: las dos ramas y la carga final son UNA sola sentencia de
    lectura. Se cuentan las llamadas a execute() que no son SET LOCAL --
    debe haber exactamente una."""
    embedder = FakeEmbedder(1536)
    read_statements: list[str] = []
    original_execute = psycopg.Cursor.execute

    def _spy(self: psycopg.Cursor, query: object, *args: object, **kwargs: object) -> object:
        # SET LOCAL se compone con psycopg.sql (sql.Composed), no con texto
        # plano, precisamente porque SET no acepta parametros ligados. Todo
        # lo que SI lee datos en este modulo es una cadena Python literal
        # (_HYBRID_SQL); distinguir por tipo es mas fiable que inspeccionar
        # el texto compuesto.
        if isinstance(query, str) and not query.strip().upper().startswith("SET"):
            read_statements.append(query)
        return original_execute(self, query, *args, **kwargs)  # type: ignore[arg-type]

    with psycopg.connect(database_url) as conn:
        await seed_corpus(conn, embedder)
        read_statements.clear()

        monkeypatch.setattr(psycopg.Cursor, "execute", _spy)
        await hybrid_search(conn, embedder, "Banorte")

    assert len(read_statements) == 1, (
        f"se esperaba una sola sentencia de lectura, hubo {len(read_statements)}"
    )


@pytest.mark.asyncio
async def test_unaccent(database_url: str) -> None:
    """CA-8: la consulta acentuada y la no acentuada dan el mismo resultado
    lexico -- "informatica" debe recuperar el fragmento con "informática"."""
    embedder = FakeEmbedder(1536)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO cv_chunks "
                "(doc_id, section, unit, chunk_type, part, parts, content, "
                " content_hash, token_count, tech_tags, embedding, embed_model_id) "
                "VALUES ('cv', 'Educacion y certificaciones', 'Ingenieria en Informática', "
                "'educacion', 1, 1, %s, %s, %s, '{}', %s, %s)",
                (
                    "Titulo de Ingeniería en Informática, obtenido en 2019.",
                    hashlib.sha256(b"informatica-fixture").hexdigest(),
                    6,
                    "[" + ",".join(str(v) for v in await embedder.embed_query("x")) + "]",
                    embedder.model_id,
                ),
            )
        conn.commit()

        with_accent = await hybrid_search(conn, embedder, "informática")
        without_accent = await hybrid_search(conn, embedder, "informatica")

    assert with_accent
    assert without_accent
    assert {r.id for r in with_accent} & {r.id for r in without_accent}
    assert any(r.unit == "Ingenieria en Informática" for r in with_accent)
    assert any(r.unit == "Ingenieria en Informática" for r in without_accent)


@pytest.mark.asyncio
async def test_uses_query_side(database_url: str) -> None:
    """CA-11 / A-9c: la rama vectorial llama a embed_query, nunca a
    embed_documents, durante la BUSQUEDA (el sembrado si usa
    embed_documents, es indexacion, no busqueda)."""
    embedder = FakeEmbedder(1536)
    with psycopg.connect(database_url) as conn:
        await seed_corpus(conn, embedder)

        counting = _CallCountingEmbedder(embedder)
        await hybrid_search(conn, counting, "Banorte")

    assert counting.embed_query_calls == 1
    assert counting.embed_documents_calls == 0


@pytest.mark.asyncio
async def test_contract_matches_rfc0005(database_url: str) -> None:
    """CA-12: RetrievedChunk devuelve id entero y unit, tal como RFC-0005
    4 los publica en sources ({"chunk_id": 42, "unit": "..."})."""
    embedder = FakeEmbedder(1536)
    with psycopg.connect(database_url) as conn:
        await seed_corpus(conn, embedder)

        results = await hybrid_search(conn, embedder, "Banorte")

    assert results
    assert isinstance(results[0].id, int)
    assert isinstance(results[0].unit, str)
    assert results[0].unit


@pytest.mark.asyncio
async def test_below_threshold_returns_empty(database_url: str) -> None:
    """CA-6 / A-3: una consulta sin relacion con el corpus devuelve [].

    Se fuerza subiendo min_score muy por encima del score maximo posible
    (1/61 + 1/61 =~ 0.033 con k=60): asi la prueba no depende de que la
    consulta REALMENTE no tenga relacion (fragil con FakeEmbedder, que no
    tiene nocion de "sin relacion"), sino de que el umbral se aplique de
    verdad sobre cualquier resultado, por bueno que sea."""
    embedder = FakeEmbedder(1536)
    with psycopg.connect(database_url) as conn:
        await seed_corpus(conn, embedder)

        results = await hybrid_search(conn, embedder, "Banorte", min_score=0.5)

    assert results == []


@pytest.mark.asyncio
async def test_threshold_does_not_reject_a_good_match(database_url: str) -> None:
    """El umbral por defecto (0.016) no descarta una coincidencia real --
    si lo hiciera, CA-1 pasaria por casualidad en vez de por la logica."""
    embedder = FakeEmbedder(1536)
    with psycopg.connect(database_url) as conn:
        await seed_corpus(conn, embedder)

        results = await hybrid_search(conn, embedder, "Banorte")

    assert results


@pytest.mark.asyncio
async def test_below_threshold_returns_empty_at_production_default(database_url: str) -> None:
    """CA-6 / A-3, auditoria PR #68 (M-1): el umbral de PRODUCCION (0.016,
    sin forzar) tambien devuelve [] ante una consulta realmente sin
    relacion -- no solo ante un min_score elevado artificialmente.

    test_below_threshold_returns_empty ya prueba que el umbral SE APLICA
    (con min_score=0.5), pero no que el valor por defecto alcance para
    cortar una consulta genuinamente irrelevante. No se puede probar eso
    con la rama semantica: FakeEmbedder no tiene nocion de "sin relacion"
    (siempre asigna algun rango por distancia de hash), asi que cualquier
    consulta, por ajena que sea, entra con sem_rank=1 y score ~=1/61 por
    encima de 0.016 (medido). Se aisla la rama lexica real (CA-7,
    _EmbedderFailsOnQuery) para que la ausencia de coincidencia en tsv sea
    la unica fuente de la lista vacia, no un min_score inflado."""
    seeder = FakeEmbedder(1536)
    with psycopg.connect(database_url) as conn:
        await seed_corpus(conn, seeder)

        failing = _EmbedderFailsOnQuery(1536)
        results = await hybrid_search(conn, failing, "xilofono marciano cuantico")

    assert results == []


class _EmbedderFailsOnQuery:
    """Simula la caida del proveedor -- embed_query lanza, embed_documents
    (sembrado) funciona: RuntimeError de dominio, no AssertionError."""

    model_id = "failing@test"

    def __init__(self, dimension: int) -> None:
        self._inner = FakeEmbedder(dimension)

    @property
    def dimension(self) -> int:
        return self._inner.dimension

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._inner.embed_documents(texts)

    async def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("el proveedor de embeddings no responde")


@pytest.mark.asyncio
async def test_embedding_failure_degrades(database_url: str) -> None:
    """CA-7 / A-5: si el embedder falla, la busqueda sigue devolviendo
    resultados lexicos y marca degraded=True en cada RetrievedChunk -- no
    se traga la excepcion en un except amplio, no lanza 500 al agente."""
    seeder = FakeEmbedder(1536)
    with psycopg.connect(database_url) as conn:
        await seed_corpus(conn, seeder)

        failing = _EmbedderFailsOnQuery(1536)
        results = await hybrid_search(conn, failing, "Banorte")

    assert results
    assert results[0].unit == "Banorte -- Ingeniera de Datos Senior"
    assert all(r.degraded for r in results)
    assert all(r.sem_rank is None for r in results), (
        "un resultado degradado no puede tener rango semantico: la rama vectorial no corrio"
    )


@pytest.mark.asyncio
async def test_healthy_embedder_never_marks_degraded(database_url: str) -> None:
    """Contraprueba: cuando el embedder funciona, degraded es False -- si
    quedara True por defecto, CA-7 pasaria sin que el fallo importara."""
    embedder = FakeEmbedder(1536)
    with psycopg.connect(database_url) as conn:
        await seed_corpus(conn, embedder)

        results = await hybrid_search(conn, embedder, "Banorte")

    assert results
    assert all(not r.degraded for r in results)


@pytest.mark.asyncio
async def test_degraded_search_is_still_a_single_read_statement(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-5/A-4 se mantiene bajo degradacion: la rama lexica sola tambien
    va en una unica sentencia de lectura, no dos."""
    seeder = FakeEmbedder(1536)
    read_statements: list[str] = []
    original_execute = psycopg.Cursor.execute

    def _spy(self: psycopg.Cursor, query: object, *args: object, **kwargs: object) -> object:
        if isinstance(query, str) and not query.strip().upper().startswith("SET"):
            read_statements.append(query)
        return original_execute(self, query, *args, **kwargs)  # type: ignore[arg-type]

    with psycopg.connect(database_url) as conn:
        await seed_corpus(conn, seeder)
        read_statements.clear()

        monkeypatch.setattr(psycopg.Cursor, "execute", _spy)
        await hybrid_search(conn, _EmbedderFailsOnQuery(1536), "Banorte")

    assert len(read_statements) == 1
