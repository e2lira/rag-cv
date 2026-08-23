# RFC-0012 — Capa de embeddings enchufable: Titan Text Embeddings V2 por defecto

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aprobado |
| **Depende de** | RFC-0006, RFC-0011 (ambos implementados) |
| **Supersede** | RFC-0001 §6 (modelo de embeddings), RFC-0002 §6 |
| **ADRs** | ADR-0004 |
| **Fecha** | 2026-08-22 |

---

## 1. Contexto y problema

El diseño original cableaba `amazon.titan-embed-text-v2:0` dentro del código. El problema no era
el modelo: era el cableado. Este RFC mantiene **Titan Text Embeddings V2 como modelo por
defecto** y lo pone detrás de una **interfaz `Embedder`** con varias implementaciones
seleccionables por configuración, entre ellas `nomic-embed-text` como contingencia.

La decisión de modelo se justifica en **ADR-0004**. Resumida: la generación ya corre sobre
Bedrock (`us.anthropic.claude-haiku-4-5-20251001-v1:0` en `us-east-2`, RFC-0013), y Titan V2 está
disponible en esa misma región. Usarlo significa **un proveedor, una credencial y una región**
para todo el sistema — y, en producción, **ningún secreto de API**: el rol de instancia de App
Runner cubre generación y embeddings.

### 1.1 Cómo se consume en desarrollo

No existe una versión local de Titan: se invoca por la API de Bedrock, y **la llamada desde
Windows es idéntica a la de producción**. Lo único que cambia es de dónde salen las credenciales.

| Entorno | Credencial | Origen |
| :--- | :--- | :--- |
| DEV (Windows) | `aws sso login --profile ragcv-dev` | `%USERPROFILE%\.aws` |
| QA (VPS Ubuntu) | Usuario IAM `rag-cv-qa-invoker` | `.env` con permisos 600 |
| PROD (App Runner) | **Rol de instancia** | Sin claves |

En los tres casos `boto3` resuelve las credenciales por su cadena por defecto: el código nunca
pasa claves explícitas. Requisito de una sola vez en cada cuenta y región: **habilitar el acceso
al modelo** en la consola de Bedrock. Si no se hace, la primera llamada devuelve
`AccessDeniedException`, que parece un problema de política IAM y no lo es.

### 1.2 Sobre el coste — el número real

Con un corpus de CV de ~60 fragmentos × ~300 tokens ≈ **20 000 tokens**, una reindexación
completa cuesta **fracciones de centavo**, y mil consultas al mes añaden otros ~20 000 tokens.
**El coste no decide nada aquí**, ni a favor ni en contra de ningún proveedor. Lo que decide es
la simplicidad de credenciales y el soporte multilingüe (ADR-0004).

## 2. Alcance

**Entra:** interfaz `Embedder`, implementación sobre Titan V2, implementaciones de contingencia
(Nomic API, Ollama), doble determinista para pruebas, normalización, dimensión como parámetro,
concurrencia de la indexación y procedimiento de cambio de modelo.

**No entra:** chunking (RFC-0002), fusión RRF (RFC-0003), empaquetado (RFC-0015), proveedor de
generación (RFC-0013).

## 3. La interfaz, y por qué tiene dos métodos aunque Titan no los necesite

```python
class Embedder(Protocol):
    """Contrato de la capa de embeddings.

    Invariantes que toda implementación debe cumplir:
      1. Los vectores devueltos tienen norma L2 == 1 (tolerancia 1e-6).
      2. len(vector) == self.dimension para todo vector devuelto.
      3. embed_documents y embed_query NO son intercambiables: cada una aplica el
         tratamiento propio de su lado. Que una implementación concreta trate
         ambos lados igual NO autoriza a fusionarlas.
      4. Ambas son deterministas: el mismo texto produce el mismo vector.
      5. model_id identifica modelo + camino ("amazon.titan-embed-text-v2:0@bedrock").
    """

    @property
    def model_id(self) -> str: ...
    @property
    def dimension(self) -> int: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embebe fragmentos destinados a ser ALMACENADOS e indexados."""

    async def embed_query(self, text: str) -> list[float]:
        """Embebe una consulta destinada a BUSCAR contra el índice."""
```

**Titan V2 es un modelo simétrico**: no distingue documento de consulta, así que sus dos métodos
hacen lo mismo. La tentación evidente es colapsarlos en un `embed(text)`. **No se hace**, y esta
es la decisión de diseño central del RFC:

- La contingencia declarada es `nomic-embed-text`, que es **asimétrico**: exige
  `search_document: ` / `search_query: ` (o el campo `task_type` si se usa por API). Usar el lado
  equivocado **no produce ningún error**: produce una recuperación peor que nadie detecta mirando
  logs.
- Si la interfaz tuviera un método único, activar la contingencia obligaría a revisar cada punto
  de llamada del sistema buscando cuáles son consultas y cuáles documentos. Con dos métodos, el
  cambio es una variable de entorno y la corrección está garantizada por el tipo.

Dicho de otro modo: **la asimetría es una propiedad del contrato, no del modelo que hoy está
detrás**. Es exactamente lo que hace que el cambio de proveedor sea barato, y por eso colapsar
los métodos es un hallazgo Bloqueante (A-1) aunque hoy parezca redundante.

## 4. Implementaciones

### 4.1 `TitanEmbedder` — implementación normativa

```python
class TitanEmbedder:
    def __init__(self, model_id: str, region: str, dimensions: int,
                 max_concurrency: int = 4) -> None:
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=Config(retries={"max_attempts": 5, "mode": "adaptive"},
                          read_timeout=20, connect_timeout=5),
        )
        self._sem = asyncio.Semaphore(max_concurrency)

    @property
    def model_id(self) -> str:
        return f"{self._model_id}@bedrock"

    @property
    def dimension(self) -> int:
        return self._dimensions            # 1024

    async def _embed_one(self, text: str) -> list[float]:
        body = json.dumps({
            "inputText": text,
            "dimensions": self._dimensions,   # explícito, no por defecto
            "normalize": True,
        })
        async with self._sem:
            # boto3 es síncrono: fuera del bucle de eventos o congela toda la API.
            resp = await asyncio.to_thread(
                self._client.invoke_model,
                modelId=self._model_id,
                contentType="application/json",
                accept="application/json",
                body=body,
            )
        vec = json.loads(resp["body"].read())["embedding"]
        return _l2_normalize(vec)             # cinturón y tirantes sobre normalize=True

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return list(await asyncio.gather(*(self._embed_one(t) for t in texts)))

    async def embed_query(self, text: str) -> list[float]:
        return await self._embed_one(text)
```

Decisiones y su motivo:

| Decisión | Motivo |
| :--- | :--- |
| `dimensions: 1024` explícito | Titan V2 admite 1024/512/256. Fijarlo evita que un cambio de valor por defecto rompa el índice en silencio |
| `normalize: True` **y** normalización propia | El contrato es nuestro, no del proveedor. pgvector compara con `<=>` y RRF asume rangos comparables |
| `asyncio.to_thread` alrededor de `invoke_model` | **boto3 es síncrono.** Sin esto, cada embedding bloquea el bucle de eventos y detiene toda la API, incluido `/healthz` |
| Semáforo de concurrencia (4) | Titan **no acepta lote**: `invoke_model` embebe un texto por llamada. Indexar 60 fragmentos son 60 llamadas. Sin límite, se dispara `ThrottlingException` contra la cuota de la cuenta |
| Reintentos `adaptive`, 5 intentos | El modo adaptativo de boto3 ya implementa el retroceso correcto ante *throttling* de Bedrock |
| Sin claves explícitas | Cadena de credenciales por defecto: SSO en DEV, usuario IAM en QA, rol de instancia en PROD |

**La ausencia de lote es la diferencia operativa que hay que tener presente.** La firma
`embed_documents(texts) -> list[list[float]]` no cambia; la implementación abre el abanico
internamente con concurrencia acotada. Quien llama no se entera, que es justo lo que la interfaz
tiene que conseguir.

**Ventana de contexto:** 8 192 tokens, muy por encima de cualquier fragmento de RFC-0002. Aun
así se conserva la comprobación de `EMBED_MAX_TOKENS` en la ingesta, porque la contingencia de
Ollama sí tiene una ventana de 2 048 y trunca en silencio.

### 4.2 `FakeEmbedder` — pruebas unitarias

Determinista y sin dependencias: `sha256(texto) → vector de la dimensión configurada →
normalizado`. Permite probar recuperación, RRF, diversificación y formateo sin red ni
credenciales, que es la mayor parte de la lógica que importa. Es la implementación por defecto de
las pruebas unitarias.

### 4.3 Contingencias

Existen porque la interfaz las hace baratas y porque son la **salida** si Titan cambia de
condiciones o se retira. Ninguna es el camino por defecto:

| Implementación | Para qué | Coste de activarla |
| :--- | :--- | :--- |
| `NomicApiEmbedder` | Independizar el retrieval de AWS; pesos abiertos (Apache 2.0) | **768 dim** ⇒ cambio de columna + reindexación (§7.1). Necesita `NOMIC_API_KEY`. Envía `task_type` explícito |
| `OllamaEmbedder` | Trabajar sin red contra `nomic-embed-text` local | 768 dim ⇒ ídem. Debe aplicar los prefijos `search_document: ` / `search_query: ` a mano: Ollama **no los añade** |

Ambas están implementadas y cubiertas por las mismas pruebas de contrato (CA-2, CA-3), de modo
que activarlas es un cambio de configuración probado, no una promesa del documento. Que la
contingencia sea asimétrica es la razón por la que la interfaz conserva dos métodos (§3).

> **Nota para pruebas manuales con Ollama.** `ollama.embeddings(model="nomic-embed-text",
> prompt=texto)` no aplica prefijo y usa el endpoint antiguo, de uno en uno. La implementación
> `OllamaEmbedder` pone el prefijo y usa `/api/embed` en lote; una prueba a mano en la consola,
> no.

## 5. Selección por configuración

| Variable | Valores | Por defecto | Descripción |
| :--- | :--- | :--- | :--- |
| `EMBEDDER` | `titan` \| `fake` \| `nomic_api` \| `ollama` | `titan` | Implementación activa |
| `EMBEDDING_DIM` | `1024` \| `768` | `1024` | **Debe** coincidir con la implementación y con el DDL |
| `TITAN_MODEL_ID` | id | `amazon.titan-embed-text-v2:0` | — |
| `AWS_REGION` | región | `us-east-2` | La misma que la generación (RFC-0013) |
| `EMBEDDER_MAX_CONCURRENCY` | entero | `4` | Llamadas simultáneas a Bedrock durante la indexación |
| `EMBED_MAX_TOKENS` | entero | `1800` | Tope por fragmento en la ingesta |
| `NOMIC_API_KEY` | secreto | — | Solo contingencia `nomic_api`. `SecretStr` |
| `OLLAMA_BASE_URL` | URL | `http://localhost:11434` | Solo contingencia `ollama` |

`Settings` valida **por rama**: si `EMBEDDER=nomic_api` y falta `NOMIC_API_KEY`, el proceso no
arranca. La fábrica en `app/retrieval/embedder.py` es el **único** módulo que conoce las
implementaciones; ni el indexador ni el retriever saben cuál está activa.

> **La firma de abajo está superada en dos puntos por RFC-0017.** Se conserva porque describe la
> forma de la fábrica —un único módulo que conoce las implementaciones— que sigue siendo el
> contrato. Lo que cambia: el cliente es **`httpx2.AsyncClient`**, no `httpx` (RFC-0017 §5.1:
> `httpx` no está instalado ni declarado), y la rama **`openai` entra**, mientras `titan`,
> `nomic_api` y `ollama` quedan diferidas y deben abortar diciendo que lo están (RFC-0017 CA-1).

```python
def build_embedder(settings: Settings, http: httpx.AsyncClient) -> Embedder:
    match settings.embedder:
        case "titan":     return TitanEmbedder(settings.titan_model_id, settings.aws_region,
                                               settings.embedding_dim,
                                               settings.embedder_max_concurrency)
        case "fake":      return FakeEmbedder(settings.embedding_dim)
        case "nomic_api": return NomicApiEmbedder(settings.nomic_api_key, settings.nomic_embed_model,
                                                  settings.embedding_dim, http)
        case "ollama":    return OllamaEmbedder(settings.ollama_base_url, settings.ollama_embed_model)
        case other:       raise ValueError(f"EMBEDDER desconocido: {other!r}")
```

`EMBEDDER=fake` **está prohibido fuera de DEV**: la validación lo rechaza si `APP_ENV != "dev"`.
Un embedder falso en producción da un servicio que responde 200 y recupera basura.

## 6. Homologación entre entornos

| Entorno | `EMBEDDER` | Credencial | Vectores comparables con PROD |
| :--- | :--- | :--- | :--- |
| DEV (Windows) | `titan` | SSO | **Sí** |
| QA (Ubuntu) | `titan` | Usuario IAM | **Sí** |
| PROD (App Runner) | `titan` | Rol de instancia | — |

El mismo modelo y la misma región en los tres entornos: un mismo texto produce el mismo vector en
local y en producción (RNF-12). Desaparece la clase de problemas "en local recupera distinto que
en producción", y no hay ninguna prueba de concordancia entre caminos que mantener.

**Contrapartida:** DEV necesita credenciales de AWS y salida a internet para indexar y consultar.
No hay desarrollo offline. La contingencia `EMBEDDER=ollama` lo permite, pero cambia el
`embed_model_id` y la dimensión, así que obliga a recrear la columna y reindexar la base local.

## 7. Consecuencias sobre el esquema

- La columna es **`VECTOR(1024)`**, la dimensión de Titan V2. (El documento base declaraba 1536,
  que corresponde a Titan G1 v1, no a V2.)
- `embed_model_id` guarda **modelo + camino** (`amazon.titan-embed-text-v2:0@bedrock`) y detecta
  el caso en que alguien indexó con una contingencia y luego consulta con Titan.
- Comprobaciones de arranque (RFC-0006 §7):

| # | Comprobación | Acción si falla |
| :--- | :--- | :--- |
| 3 | `dim(cv_chunks.embedding) == embedder.dimension` | No arranca |
| 4 | Un único `embed_model_id` en la tabla, e igual al del embedder activo | No arranca |
| 4b | `EMBEDDER != "fake"` cuando `APP_ENV != "dev"` | No arranca |
| 4c | El embedder activo responde a una llamada de prueba | `/readyz` en rojo |

### 7.1 Procedimiento de cambio de modelo (activar una contingencia)

No es una migración de columna: los vectores existentes dejan de ser comparables, y además la
dimensión cambia (1024 → 768).

```sql
BEGIN;
ALTER TABLE cv_chunks DROP COLUMN embedding;
ALTER TABLE cv_chunks ADD COLUMN embedding VECTOR(768);
DROP INDEX IF EXISTS idx_cv_chunks_hnsw;
COMMIT;
-- fuera de transacción:
CREATE INDEX CONCURRENTLY idx_cv_chunks_hnsw
  ON cv_chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
```

Después, `EMBEDDING_DIM=768`, `EMBEDDER=nomic_api` y `python -m app.ingestion.indexer --force`.
En PROD, con snapshot previo y ventana de mantenimiento: durante la reindexación la rama
vectorial no funciona (la léxica sí, degradada, RFC-0003 §6). Operación consciente, nunca
automática. Está en el runbook (RFC-0010 §9.6c).

## 8. Impacto operativo

| Aspecto | Valor |
| :--- | :--- |
| Tamaño de la imagen | ~180 MB (sin modelo embebido) |
| Memoria de la API | ~180 MB |
| Arranque en frío | ~2 s |
| Latencia de embedding de consulta | ~100–150 ms (red) |
| Indexación completa (60 fragmentos, concurrencia 4) | ~4–6 s |
| Dependencia externa en consulta | Bedrock (la misma que la generación) |
| Tamaño de App Runner | 1 vCPU / 2 GB |
| Credenciales adicionales | **Ninguna**: la misma que la generación |
| Coste mensual | Fracciones de centavo |

El presupuesto de latencia de RFC-0001 §8 no cambia: el tramo de embedding sigue siendo ~120 ms y
la generación sigue dominando.

## 9. Fallos y degradación

| Fallo | Detección | Comportamiento |
| :--- | :--- | :--- |
| `AccessDeniedException` | Primera llamada / `/readyz` | **No arranca** en QA/PROD. Causa habitual: acceso al modelo no habilitado en esa región, no la política IAM. El mensaje de error lo dice explícitamente |
| `ThrottlingException` | boto3 | Reintento adaptativo (5 intentos). En consulta: si agota, degrada a **solo rama léxica** con `degraded=true`. En indexación: `rollback` completo |
| Bedrock caído / timeout | Timeout 20 s | Consulta: degrada a rama léxica. Indexación: `rollback` completo, nunca a medias |
| `ValidationException` por texto vacío | Antes de llamar | Se filtra en la ingesta: un fragmento vacío es un fallo del troceado |
| Fragmento por encima de `EMBED_MAX_TOKENS` | Validación en la ingesta | La indexación **falla**; nunca se indexa el vector de un texto recortado |
| Respuesta con dimensión inesperada | Verificación del contrato | Se descarta y se trata como fallo del proveedor: un vector de otra dimensión corrompería el índice |
| `EMBEDDER=ollama` contra un índice `@bedrock` | Comprobación 4 de §7 | No arranca |

La degradación a solo léxica es lo que hace que una caída de Bedrock degrade el servicio en vez
de tumbarlo. Queda registrada (`DegradedRetrievals` con `reason`, RFC-0010 §5) para que la
calidad no baje en silencio.

**Riesgo concentrado, dicho claro:** con Titan, Bedrock es dependencia única para generación *y*
embeddings. Una caída regional afecta a las dos. Se acepta porque la alternativa —dos
proveedores— duplica credenciales y superficie para reducir un riesgo que la degradación a rama
léxica ya acota, y porque la contingencia a Nomic existe y está probada.

## 10. Criterios de aceptación

> **Sustituidos para la PoC por RFC-0017 §10.** Esta lista se escribió cuando Titan era la
> implementación por defecto y las cuatro implementaciones entraban en el alcance. Hoy siete de
> sus criterios (CA-4 a CA-7, CA-13, CA-14, CA-16) verifican con `test_embedder_titan.py`, CA-17
> con Nomic y Ollama, y CA-2/CA-3/CA-18 dicen «las cuatro implementaciones» — las tres
> implementaciones diferidas (ADR-0007) no se construyen, así que esos criterios **no son
> satisfacibles** y exigirlos produciría un `FAIL` mecánico contra una entrega correcta.
>
> **Los criterios vigentes para el alcance de la PoC son los de RFC-0017 §10.** De esta lista
> sobreviven, citados desde allí, CA-1 (los dos métodos), CA-2 (normalización L2), CA-8
> (`model_id` con camino) y CA-9 (`EMBED_MAX_TOKENS`, que verifica RFC-0002).
>
> Se conserva sin editar porque el día que se cierre ADR-0006 y vuelva el camino AWS, esta es la
> lista que aplica a `TitanEmbedder`.

| # | Criterio | Verificación |
| :--- | :--- | :--- |
| CA-1 | La interfaz expone `embed_documents` y `embed_query`, y **ningún** `embed()` genérico | `test_embedder_contract.py::test_no_generic_embed` |
| CA-2 | Todo vector devuelto tiene norma L2 = 1 ± 1e-6 | `test_embedder_contract.py::test_normalized`, parametrizado sobre las cuatro implementaciones |
| CA-3 | `len(vector) == embedder.dimension` en todas | `test_embedder_contract.py::test_dimension`, parametrizado |
| CA-4 | Titan recibe `dimensions` y `normalize` explícitos en el cuerpo | `test_embedder_titan.py::test_explicit_params` |
| CA-5 | `embed_documents` de N textos hace N llamadas con concurrencia acotada a `EMBEDDER_MAX_CONCURRENCY` | `test_embedder_titan.py::test_bounded_concurrency` |
| CA-6 | La llamada a boto3 no bloquea el bucle de eventos | `test_embedder_titan.py::test_does_not_block_loop` (`/healthz` responde durante un lote) |
| CA-7 | El mismo texto produce el mismo vector | `test_embedder_titan.py::test_deterministic` |
| CA-8 | `model_id` incluye el camino de servicio | `test_embedder_contract.py::test_model_id_includes_path` |
| CA-9 | Un fragmento por encima de `EMBED_MAX_TOKENS` hace fallar la ingesta | `test_indexer.py::test_oversized_chunk_fails` |
| CA-10 | `EMBEDDER=fake` con `APP_ENV=prod` impide el arranque | `test_config.py::test_fake_embedder_forbidden_in_prod` |
| CA-11 | `EMBEDDER=nomic_api` sin `NOMIC_API_KEY` impide el arranque | `test_config.py::test_embedder_required_vars` |
| CA-12 | Arrancar contra un índice con otro `embed_model_id` aborta | `test_startup_checks.py::test_model_mismatch` |
| CA-13 | `ThrottlingException` se reintenta y, si agota, degrada en consulta y hace `rollback` en indexación | `test_embedder_titan.py::test_throttling`, `test_indexer.py::test_rollback_on_embedder_failure` |
| CA-14 | Una respuesta con dimensión distinta a la esperada se rechaza | `test_embedder_titan.py::test_rejects_wrong_dimension` |
| CA-15 | Si Bedrock cae, la búsqueda devuelve resultados léxicos y marca `degraded` | `test_retrieval.py::test_embedding_failure_degrades` |
| CA-16 | El código no pasa credenciales explícitas a boto3 | `test_embedder_titan.py::test_uses_default_credential_chain` |
| CA-17 | La contingencia `nomic_api` aplica `task_type` y la `ollama` aplica los prefijos | `test_embedder_nomic_api.py::test_task_type`, `test_embedder_ollama.py::test_prefixes` |
| CA-18 | Las cuatro implementaciones pasan la **misma** suite de contrato | `test_embedder_contract.py` parametrizado |

CA-17 y CA-18 son los que hacen real la contingencia. Sin ellos, "se puede cambiar a Nomic" sería
una afirmación del documento en vez de un camino probado — y el día que hiciera falta, el detalle
de los prefijos aparecería como una degradación silenciosa de la calidad.

## 11. Riesgos

| Riesgo | Mitigación |
| :--- | :--- |
| Alguien colapsa los dos métodos en uno "porque Titan no los distingue" | Documentado en §3 + CA-1 + hallazgo Bloqueante A-1 |
| Bedrock como dependencia única de generación y embeddings | Degradación a rama léxica + contingencia a Nomic implementada y probada (CA-18) |
| `ThrottlingException` durante la indexación | Concurrencia acotada + reintento adaptativo + `rollback` completo |
| Acceso al modelo no habilitado en la región | Mensaje de error explícito + comprobación en `/readyz` + paso documentado en RFC-0011 |
| Cambio de dimensión por activar una contingencia | Procedimiento explícito (§7.1) + comprobaciones de arranque que abortan ante desajuste |
| boto3 síncrono bloqueando el bucle | `asyncio.to_thread` obligatorio + CA-6 |
| Sin red no se puede desarrollar | Contingencia `EMBEDDER=ollama`, a cambio de recrear la columna y reindexar la base local |

## Contrato de auditoría (gate ADU)

> **NO SE AUDITA CONTRA ESTA LISTA EN LA PoC. Usá el contrato de RFC-0017.**
>
> **A-6 de esta tabla exige `VECTOR(1024)` y prohíbe `1536`.** `main` declara hoy `VECTOR(1536)`
> (RFC-0006 §4.1), que es el valor **correcto** bajo RFC-0017 §4: la prohibición heredada
> correspondía a Titan G1, un modelo distinto. Un Auditor que aplique A-6 literalmente emitiría un
> Bloqueante contra código correcto y ya fusionado. A-2 de RFC-0017 la sustituye.
>
> Lo mismo con A-4 y A-9 (boto3 y cadena de credenciales de AWS: no hay AWS), A-12 y A-13 (exigen
> las cuatro implementaciones y las contingencias diferidas) y A-3 (`dimensions`/`normalize` de
> Titan).
>
> Que la advertencia viviera solo en RFC-0017 §4 no bastaba: el Auditor audita contra la lista
> **cerrada** del RFC que tiene delante, y esta la contradecía. Por eso la corrección se escribe
> aquí, donde alguien la va a leer.

| # | Comprobación | Cómo se verifica | Severidad si falla |
| :--- | :--- | :--- | :--- |
| A-1 | La interfaz conserva `embed_documents` y `embed_query`; no existe `embed()` genérico **aunque Titan sea simétrico** | CA-1 | Bloqueante |
| A-2 | La normalización L2 se hace en nuestro lado, además de `normalize: True` | CA-2 + lectura | Bloqueante |
| A-3 | `dimensions` y `normalize` viajan explícitos en el cuerpo | CA-4 | Mayor |
| A-4 | La llamada a boto3 va envuelta en `asyncio.to_thread` (o equivalente) | CA-6 | Bloqueante |
| A-5 | La concurrencia de indexación está acotada por configuración | CA-5 | Mayor |
| A-6 | El DDL declara `VECTOR(1024)`; no queda ningún `768` ni `1536` fuera de las secciones de contingencia | `grep -rn "768\|1536" app/ migrations/` | Bloqueante |
| A-7 | `Settings` valida por rama y `fake` está impedido fuera de DEV | CA-10, CA-11 | Bloqueante |
| A-8 | `model_id` incluye el camino y se persiste por fragmento | CA-8, CA-12 | Mayor |
| A-9 | No hay credenciales AWS explícitas: se usa la cadena por defecto | CA-16 | Bloqueante |
| A-10 | Una respuesta con dimensión inesperada se rechaza en vez de almacenarse | CA-14 | Bloqueante |
| A-11 | La indexación hace `rollback` completo ante fallo del proveedor | CA-13 | Bloqueante |
| A-12 | Las cuatro implementaciones pasan la misma suite de contrato | CA-18 | Mayor |
| A-13 | Las contingencias aplican correctamente `task_type` y prefijos | CA-17 | Mayor |
| A-14 | Existe la comprobación de `EMBED_MAX_TOKENS` en la ingesta | CA-9 | Mayor |
| A-15 | El procedimiento de §7.1 está en el runbook | Lectura de RFC-0010 | Menor |
