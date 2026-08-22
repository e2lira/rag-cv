# RFC-0017 — Embeddings sin AWS: `nomic-embed-text` autoalojado

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aprobado |
| **Depende de** | RFC-0012, RFC-0006, RFC-0016, RFC-0009 |
| **Supersede** | RFC-0012 §1, §4.1 (como implementación por defecto), §5 (valores por defecto), §6, §7, §8; RFC-0006 §DDL (dimensión de la columna) |
| **ADRs** | ADR-0007 |
| **Fecha** | 2026-08-22 |

---

## 1. Contexto y problema

ADR-0007 sustituye Titan V2 por `nomic-embed-text` autoalojado. Este RFC es el contrato de esa
sustitución.

Lo primero que hay que decir es lo que **no** cambia, porque es la mayor parte:

- **La interfaz `Embedder` no se toca.** `embed_documents` / `embed_query`, las cinco invariantes
  del contrato y la prohibición de un `embed()` genérico siguen exactamente como en RFC-0012 §3.
- **La fábrica no se toca.** `build_embedder` ya tiene la rama `ollama` (RFC-0012 §5).
- **La suite de contrato no se toca.** CA-1 a CA-3, CA-7 a CA-18 de RFC-0012 siguen siendo el
  criterio, parametrizados sobre las implementaciones.
- **`TitanEmbedder` no se borra.** Pasa de implementación por defecto a implementación del camino
  AWS diferido. Sigue cubierto por la misma suite.

Cambia la implementación activa, la dimensión y de dónde sale el vector. Ese es todo el alcance —
y que sea tan pequeño es consecuencia directa de que RFC-0012 §3 se negara a colapsar los dos
métodos de la interfaz cuando Titan los hacía parecer redundantes.

## 2. Alcance

**Entra:** selección de la variante del modelo por evaluación, el servicio `ollama` en el
compose, la fijación del modelo por *digest*, el cambio de dimensión y su migración, las
comprobaciones de arranque y los prefijos asimétricos.

**No entra:** la interfaz ni la suite de contrato (RFC-0012, vigentes), el chunking (RFC-0002), la
fusión RRF (RFC-0003), el proveedor de generación (RFC-0018).

## 3. Selección de la variante — se decide midiendo

`nomic-embed-text` tiene dos variantes relevantes y **el corpus está en español**, que es
precisamente la objeción que ADR-0004 levantó contra Nomic y que no ha caducado:

| Variante | Dimensión | Nota |
| :--- | :--- | :--- |
| `v1.5` | 768 | Entrenada mayoritariamente en inglés |
| `v2-moe` | 768 | Multilingüe (mezcla de expertos); mayor huella de memoria |

**Procedimiento normativo**, ejecutado antes de fijar la configuración de QA:

1. Indexar el corpus con `v1.5` y correr el conjunto dorado de RFC-0009.
2. Repetir con la variante multilingüe por la vía de servicio disponible en el entorno.
3. **Gana la que alcance Context recall ≥ 0.85** (umbral de merge de RFC-0009 §4). Es la métrica
   correcta para esta decisión porque es **determinista y no usa juez LLM**: mide si los
   `expected_chunks` fueron recuperados, que es exactamente lo que el embedder determina.
4. Empate por encima del umbral → gana la de menor huella de memoria (RFC-0016 §5).
5. **Ninguna alcanza el umbral** → la decisión falla y escala al Arquitecto. La salida documentada
   es `EMBEDDER=nomic_api` contra la variante multilingüe alojada, aceptando la credencial.
   **No se baja el umbral.**

Qué variantes sirve la versión de Ollama instalada es una **comprobación de entorno** (CA-1), no
una afirmación de este documento. Elegir la variante entrenada en inglés para un corpus español
porque es la que trae el nombre más corto es el error que este procedimiento existe para impedir.

El resultado se registra en `evals/baselines/` junto a la comparativa, que es la respuesta
documentada a "¿por qué este modelo y no el otro?".

## 4. Consecuencias sobre el esquema

La dimensión pasa de **1024 a 768**. No es una migración de columna: los vectores existentes
dejan de ser comparables y además cambia el ancho.

Puntos del repositorio que fijan la dimensión y **deben** cambiar de forma coordinada:

| Punto | Valor actual | Valor requerido |
| :--- | :--- | :--- |
| `infra/sql/001_initialize_rag_cv.sql` — columna `embedding` y su comentario | `vector(1024)` | `vector(768)` |
| RFC-0006 §DDL | `VECTOR(1024)` | Se lee junto a este RFC |
| `EMBEDDING_DIM` | `1024` | `768` |

El procedimiento es el de RFC-0012 §7.1, sin cambios:

```sql
BEGIN;
ALTER TABLE <tabla de fragmentos> DROP COLUMN embedding;
ALTER TABLE <tabla de fragmentos> ADD COLUMN embedding VECTOR(768);
DROP INDEX IF EXISTS idx_cv_chunks_hnsw;
COMMIT;
-- fuera de transacción:
CREATE INDEX CONCURRENTLY idx_cv_chunks_hnsw
  ON <tabla de fragmentos> USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
```

Después: `EMBEDDING_DIM=768`, `EMBEDDER=ollama` y reindexación completa con `--force`.

**El auditor A-6 de RFC-0012 se invierte.** Decía: *"el DDL declara `VECTOR(1024)`; no queda
ningún `768` fuera de las secciones de contingencia"*. Bajo este RFC pasa a ser: **el DDL declara
`VECTOR(768)` y no queda ningún `1024` fuera de las secciones del camino AWS diferido.** Se dice
explícitamente porque una comprobación de auditoría heredada al revés produce un `FAIL` correcto
sobre una implementación correcta, y eso quema el gate.

La verificación del *bootstrap* de base de datos que ya corre en CI
(`.github/workflows/verify-database-bootstrap.yml`) es la que debe fallar si el DDL y
`EMBEDDING_DIM` se desincronizan.

## 5. El servicio `ollama` y la fijación del modelo

`ollama` es el cuarto servicio del compose de QA (RFC-0016 §4) y **no publica puertos**:
`OLLAMA_BASE_URL=http://ollama:11434`, alcanzable solo por la red interna.

**El modelo se fija por *digest*, no por etiqueta.** Una etiqueta como `nomic-embed-text:latest`
puede apuntar a otros pesos mañana, y ese día los vectores nuevos dejan de ser comparables con los
indexados **sin que nada falle**: la dimensión sigue siendo 768, el índice sigue existiendo y la
recuperación simplemente empeora. Es el modo de fallo más caro de detectar que tiene este diseño.

Por eso `model_id` sigue llevando modelo **más camino** (`nomic-embed-text@ollama`, RFC-0012
invariante 5) y la comprobación 4 de arranque —un único `embed_model_id` en la tabla, igual al del
embedder activo— pasa a ser la defensa principal, no una formalidad.

## 6. Homologación entre entornos

| Entorno | `EMBEDDER` | Servicio | Vectores comparables |
| :--- | :--- | :--- | :--- |
| DEV (Windows) | `ollama` | Ollama nativo en la máquina del desarrollador | **Sí**, si el *digest* coincide |
| QA (VPS Ubuntu) | `ollama` | Contenedor `ollama` del compose | **Sí** |

RNF-12 se cumple **mejor que con Titan**: un solo modelo, un solo camino de servicio, mismo
*digest* en ambos entornos. La divergencia F16 vs canónico que ADR-0004 temía aparecía al mezclar
Ollama local con una API remota; aquí no hay mezcla.

**Y se recupera el desarrollo offline**, que RFC-0012 §6 declaraba perdido: DEV ya no necesita
`aws sso login` ni salida a internet para indexar y consultar. Es la contrapartida que el diseño
anterior aceptaba y que este cambio devuelve.

## 7. Los prefijos, que ahora sí importan

`nomic-embed-text` es **asimétrico**: exige `search_document: ` en los textos que se almacenan y
`search_query: ` en los que se buscan. **Ollama no los añade**: los pone `OllamaEmbedder` (RFC-0012
§4.3 y CA-17).

Usar el prefijo equivocado **no produce ningún error**. Produce una recuperación peor que nadie
detecta mirando logs. Con Titan —simétrico— CA-17 verificaba una implementación de contingencia
que nadie ejecutaba; bajo este RFC verifica **la ruta de producción de la PoC**, y por eso su
severidad de auditoría sube de `Mayor` a `Bloqueante` (A-3 de este RFC).

**Ventana de contexto:** la de Ollama es menor que los 8 192 tokens de Titan y **trunca en
silencio**. La comprobación de `EMBED_MAX_TOKENS` en la ingesta (RFC-0012 CA-9) deja de ser una
precaución y pasa a ser la que impide indexar el vector de un texto recortado.

## 8. Impacto operativo

| Aspecto | Titan (anterior) | Nomic autoalojado |
| :--- | :--- | :--- |
| Dependencia externa en consulta | Bedrock | **Ninguna**: red interna del compose |
| Credenciales | Usuario IAM en QA | **Ninguna** |
| Memoria adicional en el host | 0 | ~550 MB (`v1.5`) / ~1.4 GB (`v2-moe`) |
| Latencia de embedding de consulta | ~100–150 ms (red externa) | Local; a medir en el VPS (CA-5) |
| Lote | No lo acepta: N llamadas | `/api/embed` acepta lote |
| Coste | Fracciones de centavo | Cero |
| Tamaño de la imagen de la API | ~180 MB | ~180 MB (el modelo vive en otro contenedor) |

`EMBEDDER_MAX_CONCURRENCY` deja de proteger contra el `ThrottlingException` de una cuota de cuenta
y pasa a proteger la **CPU del VPS**: la indexación compite con PostgreSQL y con la API en el
mismo host. El valor por defecto de 4 se revisa con la medición de CA-5.

## 9. Fallos y degradación

| Fallo | Detección | Comportamiento |
| :--- | :--- | :--- |
| `ollama` no responde | Comprobación 4c de RFC-0012 §7 | Consulta: degrada a **solo rama léxica**, `degraded=true`. Indexación: `rollback` completo |
| Modelo no descargado | Primer arranque | `/readyz` en rojo, nombrando el modelo esperado |
| `embed_model_id` de la tabla ≠ embedder activo | Comprobación 4 | **No arranca** |
| `EMBEDDING_DIM` ≠ ancho de la columna | Comprobación 3 | **No arranca** |
| Respuesta con dimensión inesperada | Contrato del embedder | Se descarta: un vector de otra dimensión corrompe el índice |
| Fragmento por encima de `EMBED_MAX_TOKENS` | Validación en la ingesta | La indexación **falla** (§7) |
| Presión de memoria del host durante la indexación | `docker stats` | Se acota con `EMBEDDER_MAX_CONCURRENCY` (§8) |

## 10. Criterios de aceptación

| # | Criterio | Verificación |
| :--- | :--- | :--- |
| CA-1 | Está registrado qué variantes de Nomic sirve la versión de Ollama del entorno, y cuál se eligió | Informe de la comparativa en `evals/baselines/` |
| CA-2 | La variante elegida alcanza Context recall ≥ 0.85 sobre el conjunto dorado | `invoke evals --suite full` |
| CA-3 | El DDL declara `VECTOR(768)` y `EMBEDDING_DIM=768`; arrancar con uno de los dos desincronizado aborta | `verify-database-bootstrap.yml` + `test_startup_checks.py::test_dim_mismatch` |
| CA-4 | El modelo está fijado por *digest* y el `embed_model_id` persistido lo refleja | Lectura de la configuración + consulta a la tabla |
| CA-5 | Latencia p95 del embedding de consulta medida en el VPS y dentro del presupuesto de RNF-3 | Ejecución de la evaluación en QA |
| CA-6 | `OllamaEmbedder` aplica `search_document: ` y `search_query: ` en el lado correcto | `test_embedder_ollama.py::test_prefixes` (CA-17 de RFC-0012) |
| CA-7 | La indexación completa no provoca OOM en el VPS | CA-4 de RFC-0016 |
| CA-8 | Con `ollama` detenido, la consulta responde con resultados léxicos y `degraded=true` | `test_retrieval.py::test_embedding_failure_degrades` |
| CA-9 | Indexar y consultar funcionan **sin red externa** en DEV | Ejecución con la interfaz de red deshabilitada |
| CA-10 | `TitanEmbedder` sigue existiendo y pasando la suite de contrato | `test_embedder_contract.py` parametrizado |

## 11. Riesgos

| Riesgo | Mitigación |
| :--- | :--- |
| Se elige `v1.5` por comodidad y la calidad en español cae | §3 hace la elección un resultado medido, con umbral y salida documentada |
| La etiqueta del modelo cambia de pesos y los vectores dejan de ser comparables en silencio | Fijación por *digest* (§5) + comprobación 4 de arranque |
| Los prefijos se aplican al revés y la calidad cae sin error | CA-6, elevado a Bloqueante en el contrato de auditoría |
| Queda un `1024` heredado y el auditor lo interpreta con la regla vieja | §4 invierte A-6 de RFC-0012 explícitamente |
| Truncado silencioso por ventana de contexto menor | `EMBED_MAX_TOKENS` verificado en la ingesta (§7) |
| La indexación satura el VPS y afecta a la API | `EMBEDDER_MAX_CONCURRENCY` revisado con la medición de CA-5 |
| Alguien borra `TitanEmbedder` "porque ya no se usa" | CA-10: es el camino AWS diferido, no código muerto |

## Contrato de auditoría (gate ADU)

| # | Comprobación | Cómo se verifica | Severidad si falla |
| :--- | :--- | :--- | :--- |
| A-1 | La interfaz conserva `embed_documents` y `embed_query`; no existe `embed()` genérico | CA-1 de RFC-0012 | Bloqueante |
| A-2 | El DDL declara `VECTOR(768)`; no queda ningún `1024` ni `1536` fuera de las secciones del camino AWS diferido | `rg -n "1024\|1536" app/ migrations/ infra/sql/` | Bloqueante |
| A-3 | `OllamaEmbedder` aplica los prefijos en el lado correcto | CA-6 | **Bloqueante** (era Mayor en RFC-0012: ahora es la ruta de producción) |
| A-4 | El modelo está fijado por *digest*, no por etiqueta móvil | CA-4 | Bloqueante |
| A-5 | La elección de variante está respaldada por la comparativa de evaluación, no por preferencia | CA-1, CA-2 | Bloqueante |
| A-6 | La normalización L2 se hace en nuestro lado | CA-2 de RFC-0012 | Bloqueante |
| A-7 | El servicio `ollama` no publica puertos al host | A-3 de RFC-0016 | Bloqueante |
| A-8 | La indexación hace `rollback` completo ante fallo del embedder | CA-13 de RFC-0012 | Bloqueante |
| A-9 | `TitanEmbedder` sigue presente y cubierto por la suite de contrato | CA-10 | Mayor |
| A-10 | La comprobación de `EMBED_MAX_TOKENS` sigue activa en la ingesta | CA-9 de RFC-0012 | Mayor |
| A-11 | La latencia de embedding medida en el VPS cabe en RNF-3 | CA-5 | Mayor |
| A-12 | El procedimiento de reindexación quedó registrado en el runbook | RFC-0010 §9.6c | Menor |
