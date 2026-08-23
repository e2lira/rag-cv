# RFC-0017 — Embeddings sin AWS: `text-embedding-3-small` de OpenAI

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aprobado |
| **Depende de** | RFC-0012, RFC-0006, RFC-0016, RFC-0009 |
| **Supersede** | RFC-0012 §1, §4.1 (como implementación por defecto), §5 (valores por defecto y ramas), §6, §7, §8; RFC-0006 §DDL (dimensión de la columna) |
| **ADRs** | ADR-0007 |
| **Fecha** | 2026-08-22 |

---

## 1. Contexto y problema

ADR-0007 sustituye Titan V2 por `text-embedding-3-small` de OpenAI. Este RFC es el contrato de esa
sustitución.

Lo primero es lo que **no** cambia, porque es la mayor parte:

- **La interfaz `Embedder` no se toca.** `embed_documents` / `embed_query`, las cinco invariantes
  del contrato y la prohibición de un `embed()` genérico siguen exactamente como en RFC-0012 §3.
- **La fábrica no cambia de forma**, solo gana una rama. Sigue siendo el único módulo que conoce
  implementaciones concretas.
- **La suite de contrato de RFC-0012 sigue siendo el criterio.** Se implementa parametrizada, de
  modo que añadir una implementación sea añadir un caso, no escribir pruebas nuevas.
- **`TitanEmbedder`, `NomicApiEmbedder` y `OllamaEmbedder` no se retiran del diseño.** Siguen
  siendo el camino AWS diferido y las contingencias documentadas.

**Precisión necesaria sobre qué hay que construir.** RFC-0012 describe la interfaz, la fábrica y
cuatro implementaciones, pero **nada de eso está implementado todavía**: el repositorio contiene
documentación y el DDL. Este RFC se lee como delta sobre un diseño, no sobre código existente.

Lo que entra en el alcance de la PoC es **`FakeEmbedder` y `OpenAIEmbedder`**, más la interfaz, la
fábrica y la suite de contrato de RFC-0012. Las otras tres quedan **diferidas con su camino**:
`TitanEmbedder` con AWS (ADR-0006) y las de Nomic con el autoalojamiento que este host no sostiene
(ADR-0007). Exigirlas ahora obligaría a implementar un embedder de Bedrock en una PoC que
eliminó AWS, que es precisamente el tipo de contradicción que el Definition of Ready existe para
cazar.

Lo que sí cambia, y hay que decirlo sin rodeos: **hay que escribir código nuevo.** La fábrica de
RFC-0012 §5 solo contempla `titan | fake | nomic_api | ollama`. No existe una rama de OpenAI para
embeddings, y **el `openai_compatible` de RFC-0013 no sirve**: esa es la capa de *generación*.
Confundirlas es el error previsible de este cambio.

## 2. Alcance

**Entra:** la rama `openai` de la fábrica, el contrato de `OpenAIEmbedder`, la fijación del modelo,
el cambio de dimensión y su migración, el lote, y las comprobaciones de arranque.

**No entra:** la interfaz ni la suite de contrato (RFC-0012, vigentes), el chunking (RFC-0002), la
fusión RRF (RFC-0003), el proveedor de generación (RFC-0018).

## 3. El modelo está designado; la evaluación lo verifica

**`text-embedding-3-small` es el modelo de la PoC.** No es el resultado de una comparativa entre
candidatos: es una decisión tomada (ADR-0007), y este RFC no la reabre.

Lo que sí queda es **verificar que funciona**, y conviene separar bien las dos cosas porque se
confunden con facilidad:

- *Elegir modelo* sería una comparativa entre alternativas. **No se hace**: está decidido.
- *Verificar el retrieval* es comprobar que el sistema recupera los fragmentos correctos. **Se hace
  igual**, porque el umbral de **Context recall ≥ 0.85** ya es gate de merge en RFC-0009 §4, con
  independencia de qué modelo esté detrás.

Esa segunda parte no es ceremonia de selección: si el *context recall* está por debajo del umbral,
el agente no recupera los fragmentos que necesita y **responde mal o se abstiene cuando no debería**.
Eso no es un matiz de producción que una PoC pueda saltarse — es la diferencia entre una demo que
funciona y una que no.

Es además la métrica correcta para este punto porque es **determinista y no usa juez LLM**: mide si
los `expected_chunks` fueron recuperados, que es exactamente lo que el embedder determina. Un juez
LLM aquí mediría la redacción, no la recuperación.

**Si no se alcanza el umbral**, no es una decisión que falla: es un **hallazgo** que escala al
Arquitecto. La salida documentada es `text-embedding-3-large` (3072 dimensiones, varias veces el
coste), y **el umbral no se baja** para que el número cuadre.

El resultado se registra en `evals/baselines/` como línea base del sistema.

## 4. Consecuencias sobre el esquema — y una trampa de auditoría

La dimensión pasa de **1024 a 1536**. No es una migración de columna: los vectores existentes dejan
de ser comparables y además cambia el ancho.

| Punto | Valor actual | Valor requerido |
| :--- | :--- | :--- |
| `infra/sql/001_initialize_rag_cv.sql` — columna `embedding` y su comentario | `vector(1024)` | `vector(1536)` |
| RFC-0006 §DDL | `VECTOR(1024)` | Se lee junto a este RFC |
| `EMBEDDING_DIM` | `1024` | `1536` |

El procedimiento es el de RFC-0012 §7.1, sin cambios de forma:

```sql
BEGIN;
ALTER TABLE <tabla de fragmentos> DROP COLUMN embedding;
ALTER TABLE <tabla de fragmentos> ADD COLUMN embedding VECTOR(1536);
DROP INDEX IF EXISTS idx_cv_chunks_hnsw;
COMMIT;
-- fuera de transacción:
CREATE INDEX CONCURRENTLY idx_cv_chunks_hnsw
  ON <tabla de fragmentos> USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
```

Después: `EMBEDDING_DIM=1536`, `EMBEDDER=openai` y reindexación completa con `--force`.

**Aquí está la trampa, y hay que decirla en voz alta.** RFC-0006 §DDL advierte que el documento
base declaraba `1536` y que ese valor **era erróneo**: correspondía a Titan G1 v1, no a Titan V2.
RFC-0012 A-6 convirtió esa advertencia en comprobación de auditoría — *"no queda ningún `768` ni
`1536` fuera de las secciones de contingencia"*.

Bajo este RFC, **`1536` pasa a ser el valor correcto**, por un modelo completamente distinto y por
una razón que no tiene nada que ver con la anterior. Un auditor que aplique la regla heredada verá
`1536`, lo leerá como el error histórico de Titan G1 y emitirá un `FAIL` **correcto según su regla
y equivocado según el diseño**. Eso quema el gate G4, que es precisamente lo que ADU existe para
proteger.

La comprobación vigente es **A-2 de este RFC**, y sustituye a A-6 de RFC-0012.

La verificación de *bootstrap* que ya corre en CI
(`.github/workflows/verify-database-bootstrap.yml`) es la que debe fallar si el DDL y
`EMBEDDING_DIM` se desincronizan.

## 5. `OpenAIEmbedder` — contrato de la implementación

| Decisión | Motivo |
| :--- | :--- |
| Modelo fijado a `text-embedding-3-small`, explícito en la configuración | Pesos cerrados: si el proveedor cambia el modelo detrás del nombre, la salida es *otro* modelo y el índice deja de ser comparable **sin que nada falle** |
| El parámetro de dimensión **no se envía**: se usan las 1536 nativas | Acortar solo tendría sentido para evitar el cambio de DDL, y el DDL cambia igual (§4). Sería menos información por vector a cambio de nada |
| Verificar que la respuesta tiene 1536 componentes | Un vector de otra dimensión corrompe el índice: se rechaza en vez de almacenarse |
| Normalización L2 en nuestro lado | El contrato es nuestro, no del proveedor (RFC-0012 invariante 1). pgvector compara con `<=>` y RRF asume rangos comparables |
| **Lote real**: el endpoint acepta un array de entradas | A diferencia de Titan, que exigía una llamada por texto. `embed_documents` hace **una** llamada por lote, no N |
| Cliente asíncrono (`httpx`), no bloqueante | La fábrica ya recibe un `httpx.AsyncClient` (RFC-0012 §5). No se repite el error de bloquear el bucle de eventos |
| `model_id` = `text-embedding-3-small@openai` | Modelo **más camino** (RFC-0012 invariante 5): detecta que se indexó con una implementación y se consulta con otra |

**El lote cambia el perfil operativo.** `EMBEDDER_MAX_CONCURRENCY` existía para no chocar contra la
cuota de Bedrock con 60 llamadas sueltas. Con lote, la indexación completa es una o dos llamadas y
esa variable deja de ser la palanca relevante; lo que importa pasa a ser el tamaño de lote y el
tope de tokens por petición.

## 6. Homologación entre entornos

| Entorno | `EMBEDDER` | Credencial | Vectores comparables |
| :--- | :--- | :--- | :--- |
| DEV (Windows) | `openai` | `OPENAI_API_KEY` en `.env` local | **Sí** |
| QA (VPS Ubuntu) | `openai` | `OPENAI_API_KEY` en `$RAG_CV_HOME/.env`, permisos `600` | **Sí** |

RNF-12 se cumple: un mismo texto produce el mismo vector en DEV y en QA, porque ambos llaman al
mismo modelo por el mismo camino. No hay cuantización local ni *digest* que fijar.

**Y se pierde el desarrollo offline**, que el plan autoalojado habría devuelto. DEV necesita red y
credencial para indexar y consultar. La contingencia `EMBEDDER=ollama` sigue implementada para
quien tenga cómputo local, a cambio de recrear la columna a 768 y reindexar la base local.

## 7. Por qué la interfaz conserva dos métodos aunque este modelo sea simétrico

`text-embedding-3-small` **es simétrico**: no distingue documento de consulta, así que
`embed_documents` y `embed_query` hacen lo mismo. La tentación de colapsarlos en un `embed(text)`
vuelve, exactamente igual que con Titan.

**No se hace, y el argumento de RFC-0012 §3 sigue intacto:** la contingencia `nomic-embed-text` es
**asimétrica** —exige `search_document: ` / `search_query: `— y usar el lado equivocado **no produce
ningún error**: produce una recuperación peor que nadie detecta mirando logs. Con dos métodos,
activar la contingencia es una variable de entorno y la corrección la garantiza el tipo.

Colapsarlos sigue siendo hallazgo **Bloqueante** (RFC-0012 A-1).

Consecuencia menor pero real: CA-17 de RFC-0012 —los prefijos de las contingencias— vuelve a
verificar un camino que **no** está en producción. Conserva su severidad original (`Mayor`), no la
elevada que tendría si Nomic fuera la ruta activa.

**Ventana de contexto.** La del modelo está muy por encima de cualquier fragmento de RFC-0002. Aun
así se conserva la comprobación de `EMBED_MAX_TOKENS` en la ingesta, porque las contingencias
locales sí truncan en silencio.

## 8. Impacto operativo

| Aspecto | Titan (anterior) | OpenAI `3-small` |
| :--- | :--- | :--- |
| Dependencia externa en consulta | Bedrock | API de OpenAI |
| Credenciales | Usuario IAM en QA | `OPENAI_API_KEY` (**segundo** secreto, junto al de Anthropic) |
| Cómputo y memoria en el host | 0 | 0 |
| Latencia de embedding de consulta | ~100–150 ms | ~100–150 ms (a medir, CA-5) |
| Lote | No lo acepta: N llamadas | **Sí**: una llamada por lote |
| Dimensión | 1024 | **1536** |
| Coste | Fracciones de céntimo | Fracciones de céntimo |

El presupuesto de latencia de RFC-0001 §8 **vuelve a su supuesto original**: el tramo de embedding
es una espera de red de ~120 ms y la generación sigue dominando. Con el plan autoalojado ese tramo
habría pasado a ser cómputo local compitiendo por 2 núcleos (RFC-0016 §5); esa presión desaparece.

## 9. Fallos y degradación

| Fallo | Detección | Comportamiento |
| :--- | :--- | :--- |
| API de OpenAI caída o con *timeout* | Cliente | Consulta: degrada a **solo rama léxica**, `degraded=true` (RFC-0003 §6). Indexación: `rollback` completo |
| Clave inválida o revocada | Arranque / comprobación 4c de RFC-0012 §7 | `/readyz` en rojo. No se sirve tráfico con un embedder que no responde |
| Límite de tasa (429) | Respuesta | Retroceso y reintento; si agota, degrada en consulta y hace `rollback` en indexación |
| `embed_model_id` de la tabla ≠ embedder activo | Comprobación 4 | **No arranca** |
| `EMBEDDING_DIM` ≠ ancho de la columna | Comprobación 3 | **No arranca** |
| Respuesta con dimensión inesperada | Contrato del embedder | Se descarta: un vector de otra dimensión corrompe el índice |
| Fragmento por encima de `EMBED_MAX_TOKENS` | Validación en la ingesta | La indexación **falla**; nunca se indexa el vector de un texto recortado |
| El proveedor cambia el modelo detrás del nombre | **Sin detección automática** | Deuda declarada en ADR-0007. Se acota persistiendo `embed_model_id` por fragmento |

La caída del embedder **no** coincide con la del generador: son proveedores distintos. Una caída de
OpenAI degrada la recuperación a rama léxica sin tocar la generación, y una de Anthropic no afecta
al índice. Es una mejora real frente al diseño original, donde Bedrock era ambos.

## 10. Criterios de aceptación

| # | Criterio | Verificación |
| :--- | :--- | :--- |
| CA-1 | La fábrica acepta `EMBEDDER=openai` y devuelve `OpenAIEmbedder`; un valor desconocido aborta con la lista de válidos | `test_embedder_factory.py` parametrizado sobre las cinco ramas |
| CA-2 | El retrieval con `text-embedding-3-small` alcanza Context recall ≥ 0.85 sobre el conjunto dorado | `invoke evals --suite full`, resultado en `evals/baselines/` |
| CA-3 | El DDL declara `VECTOR(1536)` y `EMBEDDING_DIM=1536`; arrancar con uno de los dos desincronizado aborta | `verify-database-bootstrap.yml` + `test_startup_checks.py::test_dim_mismatch` |
| CA-4 | `embed_documents` de N textos hace **una** llamada con los N en el cuerpo | `test_embedder_openai.py::test_batches_in_one_call` |
| CA-5 | Latencia p95 del embedding de consulta medida y dentro del presupuesto de RNF-3 | Ejecución de la evaluación en QA |
| CA-6 | Una respuesta con dimensión distinta de 1536 se rechaza en vez de almacenarse | `test_embedder_openai.py::test_rejects_wrong_dimension` |
| CA-7 | `model_id` es `text-embedding-3-small@openai` y se persiste por fragmento | `test_embedder_contract.py::test_model_id_includes_path` + consulta a la tabla |
| CA-8 | `EMBEDDER=openai` sin `OPENAI_API_KEY` impide el arranque | `test_config.py::test_embedder_required_vars` |
| CA-9 | Con la API caída, la consulta devuelve resultados léxicos y marca `degraded` | `test_retrieval.py::test_embedding_failure_degrades` |
| CA-10 | La indexación hace `rollback` completo ante fallo del proveedor | `test_indexer.py::test_rollback_on_embedder_failure` |
| CA-11 | `FakeEmbedder` y `OpenAIEmbedder` pasan la **misma** suite de contrato, parametrizada. Cualquier implementación que se añada después entra por esa suite | `test_embedder_contract.py` parametrizado |
| CA-12 | La clave nunca aparece en logs ni en trazas | `SecretStr` + inspección de la salida en una corrida completa |

## 11. Riesgos

| Riesgo | Mitigación |
| :--- | :--- |
| **Un auditor aplica A-6 de RFC-0012 y falla un `1536` correcto** | §4 lo declara explícitamente y A-2 de este RFC sustituye a aquella comprobación |
| Alguien intenta usar `openai_compatible` de RFC-0013 creyendo que da embeddings | §1 lo advierte; CA-1 verifica que la rama de embeddings es propia |
| El proveedor cambia el modelo detrás del nombre y la recuperación empeora en silencio | Identificador explícito + `embed_model_id` por fragmento + comprobación 4 de arranque |
| Alguien colapsa los dos métodos "porque este modelo es simétrico" | §7 + CA-1 de RFC-0012 + hallazgo Bloqueante A-1 |
| Segundo secreto de larga vida en el VPS | `SecretStr`, `600` en el `.env`, `gitleaks` en CI y exclusión en el `rsync` (RFC-0020 §6) |
| Se baja el umbral de RFC-0009 porque "es solo una PoC" | §3 lo prohíbe: el umbral mide si el sistema recupera, no cuán formal es el entorno. Nombra el siguiente candidato |
| Los fragmentos del CV salen hacia un tercero más | Declarado en ADR-0007. Reabre la decisión si aparece un requisito de residencia de datos |

## Contrato de auditoría (gate ADU)

| # | Comprobación | Cómo se verifica | Severidad si falla |
| :--- | :--- | :--- | :--- |
| A-1 | La interfaz conserva `embed_documents` y `embed_query`; no existe `embed()` genérico **aunque este modelo sea simétrico** | CA-1 de RFC-0012 | Bloqueante |
| A-2 | El DDL declara `VECTOR(1536)` y no queda ningún `1024` fuera de las secciones del camino AWS diferido. **Sustituye a A-6 de RFC-0012**, cuya prohibición de `1536` correspondía a otro modelo | `rg -n "1024" app/ migrations/ infra/sql/` | Bloqueante |
| A-3 | La normalización L2 se hace en nuestro lado | CA-2 de RFC-0012 | Bloqueante |
| A-4 | El identificador del modelo es explícito y `embed_model_id` incluye el camino | CA-7 | Bloqueante |
| A-5 | Una respuesta con dimensión inesperada se rechaza en vez de almacenarse | CA-6 | Bloqueante |
| A-6 | La indexación hace `rollback` completo ante fallo del proveedor | CA-10 | Bloqueante |
| A-7 | El retrieval alcanza el umbral de RFC-0009, y si no lo alcanza consta el hallazgo escalado en vez de un umbral rebajado | CA-2 | Bloqueante |
| A-8 | La clave es `SecretStr` y no aparece en logs | CA-12 | Bloqueante |
| A-9 | `embed_documents` usa el lote del proveedor, no N llamadas sueltas | CA-4 | Mayor |
| A-10 | Las implementaciones del alcance pasan la misma suite de contrato, y ninguna implementación diferida se exige como requisito de entrega | CA-11 | Mayor |
| A-11 | La llamada no bloquea el bucle de eventos | Lectura + CA-6 de RFC-0012 | Mayor |
| A-12 | La comprobación de `EMBED_MAX_TOKENS` sigue activa en la ingesta | CA-9 de RFC-0012 | Mayor |
| A-13 | La latencia de embedding medida cabe en RNF-3 | CA-5 | Mayor |
| A-14 | El procedimiento de reindexación quedó registrado en el runbook | RFC-0010 §9.6c | Menor |
