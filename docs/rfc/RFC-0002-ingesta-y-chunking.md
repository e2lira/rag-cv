# RFC-0002 — Ingesta del CV, normalización y chunking

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aprobado |
| **Depende de** | RFC-0001, RFC-0006, **RFC-0017** (el *embedder* que consume la ingesta) |
| **Superseded en parte por** | RFC-0016 §3.3 (§3: el corpus no va en Git); RFC-0012 → RFC-0017 (§6: modelo y proveedor) |
| **Fecha** | 2026-08-22 |

---

## 1. Contexto y problema

La calidad de un sistema RAG sobre un corpus pequeño se decide casi por completo en la
ingesta. Un CV tiene una estructura fuertemente jerárquica (perfil → experiencia → empresa →
proyecto → logros) y un vocabulario denso en entidades (tecnologías, empresas, años). Trocear
por número de caracteres destruye esa estructura y produce fragmentos que empiezan a mitad de
una viñeta, sin decir a qué empleo pertenecen.

Este RFC define cómo el corpus Markdown se convierte en fragmentos recuperables **que se
explican solos**.

## 2. Alcance

**Entra:** formato obligatorio del corpus, normalización, estrategia de chunking, metadatos,
enriquecimiento de contexto, cálculo de embeddings, indexación idempotente y CLI de ingesta.

**No entra:** la consulta (RFC-0003), el DDL (RFC-0006), la ingesta de PDF/LinkedIn (fuera del
PRD), la traducción automática del corpus.

## 3. Fuente de verdad: `corpus/cv.md`

> **El corpus NO se versiona en Git (RFC-0016 §3.3).** La frase de abajo decía lo contrario y
> quedó superseded: el repositorio es **público** y un CV contiene datos personales. El fichero
> vive en el VPS, en la ruta que indica `CORPUS_PATH`, fuera del repositorio y de la imagen, para
> que actualizar el CV no exija un despliegue.
>
> El resto de esta sección —*front-matter*, jerarquía de encabezados, rangos de fechas, límite de
> 400 palabras por unidad y prohibición de datos sensibles— **sigue vigente y es normativa**: el
> cargador rechaza la ingesta si se incumple.
>
> `.gitignore` ya ignora `corpus/`, citando esa misma decisión. Este banner existe porque la
> supersesión estaba declarada en RFC-0016 y en el código, pero era invisible desde aquí — y esto
> es lo primero que lee quien va a implementar.

Un único archivo Markdown. Estructura obligatoria:

```markdown
---
persona: "Nombre Apellido"
titular: "Full Stack AI Engineer"
ubicacion: "Ciudad de México, México"
actualizado: "2026-08-22"
idiomas_corpus: ["es"]
---

# Perfil

<resumen de 5–8 líneas en primera persona>

# Experiencia

## <Empresa> — <Puesto>            <!-- 2022-03 .. 2025-11 -->
**Contexto:** <qué hacía la empresa / el equipo>
**Responsabilidad:** <alcance, tamaño de equipo, presupuesto si aplica>
**Logros:**
- <logro con métrica>
**Stack:** Python, FastAPI, AWS, PostgreSQL

# Proyectos

## <Nombre del proyecto>
**Problema:** …
**Decisión técnica:** …
**Resultado:** …
**Stack:** …

# Habilidades

## Lenguajes y frameworks
## Cloud e infraestructura
## Datos e IA

# Educación y certificaciones

# Preguntas frecuentes            <!-- respuestas curadas a preguntas recurrentes -->

## ¿Está disponible para reubicación?
…
```

**Reglas del corpus** (validadas por el cargador, fallan la ingesta si se incumplen):

1. Front-matter YAML obligatorio con `persona`, `titular` y `actualizado`.
2. Solo se usan encabezados `#` (sección) y `##` (unidad). `###` está prohibido: si algo
   necesita tres niveles, es una unidad nueva.
3. Cada `##` bajo `# Experiencia` incluye el rango de fechas en un comentario HTML
   `<!-- AAAA-MM .. AAAA-MM -->` o el literal `actual`.
4. Ninguna unidad `##` supera las 400 palabras. Si las supera, se divide en dos unidades.
5. Los datos sensibles (documento de identidad, domicilio, teléfono personal) están prohibidos;
   el validador rechaza patrones de CURP/RFC/teléfono/email personal fuera de `contacto`.

La sección **Preguntas frecuentes** es una decisión deliberada: convierte las preguntas
esperables sin respuesta natural en el CV (disponibilidad, modalidad de trabajo, expectativas
de rol) en evidencia recuperable, evitando que el modelo especule.

## 4. Estrategia de chunking

**Unidad de troceado = la unidad `##`.** Cada `##` es un fragmento; los párrafos sueltos bajo
un `#` sin `##` forman un fragmento propio de esa sección.

Sobre esa base se aplican tres refinamientos:

### 4.1 Enriquecimiento contextual (*contextual retrieval*)

Cada fragmento se almacena con una **cabecera de contexto** generada de forma determinista
(sin LLM), anteponiendo su ruta jerárquica y sus metadatos clave:

```text
[Sección: Experiencia > Banorte — Ingeniero de Datos Senior | 2022-03 a 2025-11 | Stack: Python, AWS, PostgreSQL]
Contexto: ...
Responsabilidad: ...
Logros: ...
```

Esa cabecera se incluye **tanto en el texto que se embebe como en el texto que se devuelve al
agente**. Es lo que permite que un fragmento sobre "logros" siga siendo interpretable cuando
se recupera aislado, y lo que hace que una consulta como *"experiencia en Banorte"* acierte
léxicamente aunque el cuerpo del fragmento no repita el nombre de la empresa.

### 4.2 División de unidades largas

Si una unidad supera **1 200 caracteres** tras el enriquecimiento, se divide por viñetas o
párrafos en sub-fragmentos de ~800 caracteres con **solapamiento de 120 caracteres**,
repitiendo la cabecera de contexto en cada uno y numerándolos (`parte 1/3`). El solapamiento
solo se aplica dentro de una unidad, nunca entre unidades distintas.

### 4.3 Fragmento de resumen global

Se genera un fragmento sintético `perfil_global` que concatena el front-matter, el Perfil y
los titulares de toda la experiencia (empresa, puesto, fechas, stack). Cubre las preguntas
panorámicas —*"¿cuál es su trayectoria?"*, *"¿cuántos años lleva en IA?"*— que ningún
fragmento individual responde bien.

> **`perfil_global` es la `unit`, no el `chunk_type`.** El esquema vigente restringe
> `chunk_type` a `('perfil','experiencia','proyecto','habilidad','educacion','faq')` —
> `CONSTRAINT` del DDL de RFC-0006, no una convención— así que un fragmento con
> `chunk_type='perfil_global'` **lo rechaza la base de datos**. Este fragmento se identifica
> como `chunk_type='perfil'`, `unit='perfil_global'`, `part=1`, `parts=1`, y esa terna es la que
> lo hace único bajo `uq_chunk (doc_id, unit, part)`.
>
> Sin esto, CA-4 y A-6 —que lo nombran sin decir en qué columna vive— no se pueden satisfacer
> literalmente contra el esquema que ya está en `main`.

**Justificación del tamaño:** con `top_k=5` y fragmentos de ≤1 200 caracteres, el contexto
inyectado ronda 1 500–2 000 tokens. Es suficiente para respuestas fundamentadas y mantiene el
costo por turno dentro de RNF-5 con margen para 6 turnos de historial.

## 5. Metadatos por fragmento

| Campo | Tipo | Ejemplo | Uso |
| :--- | :--- | :--- | :--- |
| `doc_id` | `text` | `cv` | Multi-corpus futuro |
| `section` | `text` | `Experiencia` | Filtro y trazabilidad |
| `unit` | `text` | `Banorte — Ingeniero de Datos Senior` | Cita mostrada al usuario |
| `chunk_type` | `enum` | `experiencia` \| `proyecto` \| `habilidad` \| `educacion` \| `faq` \| `perfil` | Filtro y diversificación |
| `date_start` / `date_end` | `date` \| `null` | `2022-03-01` / `null` (actual) | Preguntas temporales |
| `tech_tags` | `text[]` | `{python,aws,postgresql}` | Filtro léxico y facetas |
| `part` / `parts` | `int` | `1` / `3` | Reensamblado y cita |
| `content_hash` | `char(64)` | SHA-256 del texto enriquecido | Idempotencia |
| `token_count` | `int` | `280` | Control de presupuesto de contexto |

`tech_tags` se extrae de la línea `**Stack:**` normalizando a minúsculas y aplicando un
diccionario de sinónimos (`postgres`→`postgresql`, `js`→`javascript`, `k8s`→`kubernetes`)
que vive en `app/ingestion/synonyms.py`. El mismo diccionario se usa en la expansión de la
consulta (RFC-0003 §5).

## 6. Cálculo de embeddings

> **Modificado por RFC-0012, y este por RFC-0017.** El modelo y su forma de invocación se
> definen allí; aquí solo queda lo que la ingesta debe garantizar. La cadena importa: RFC-0012
> designaba `TitanEmbedder` como implementación normativa, y **RFC-0017 §1 la difirió** junto con
> el resto de AWS (ADR-0007). El *embedder* de la PoC es `OpenAIEmbedder`
> (`text-embedding-3-small`, dimensión **1536**), y las tres implementaciones diferidas abortan
> el arranque con `DeferredEmbedderError` si `EMBEDDER` las nombra.

- La ingesta llama a **`embedder.embed_documents(...)`**, nunca a `embed_query`. La distinción
  es la que decide la calidad de la recuperación (RFC-0012 §3): el indexador produce
  **documentos**, no consultas.
- Se embebe **el texto enriquecido completo** (cabecera de contexto + cuerpo). Cómo se reparten
  las llamadas es asunto del `Embedder`: `OpenAIEmbedder` manda el lote en una sola petición
  (RFC-0017 CA-4); otras implementaciones podrían abrir el abanico con concurrencia acotada. El
  indexador solo llama a `embed_documents(textos)`.
- El indexador no conoce el modelo ni el proveedor: recibe un `Embedder` construido por la
  fábrica. Cambiar de modelo no toca este módulo.
- Antes de embeber, cada fragmento se valida contra `EMBED_MAX_TOKENS` (1 800). Si lo supera, la
  indexación **falla**: nunca se indexa el vector de un texto truncado en silencio.

> **`EMBED_MAX_TOKENS` y `CORPUS_PATH` no existen todavía en `Settings`.** Las define el contrato
> —`EMBED_MAX_TOKENS` en RFC-0012 §6, `CORPUS_PATH` en RFC-0011 §4.5 y RFC-0016 §7— y las dos
> están en `.env.example`, pero `app/core/settings.py` no las expone. **Las agrega este RFC**,
> como RFC-0021 §4 tuvo que agregar `DATABASE_URL` por la misma razón: un contrato que exige una
> variable que la clase no tiene obliga al Desarrollador a inventarse de dónde sale.
>
> `CORPUS_PATH` es el valor por defecto del `--corpus` de §8, no un sustituto: la CLI puede
> apuntar a otro fichero, y en QA la ruta es absoluta (RFC-0016 §7).
- La dimensión y la normalización son responsabilidad del `Embedder` y están en su contrato
  (norma L2 = 1, `len(vector) == dimension`).
- Coste de una indexación completa de ~60 fragmentos: fracciones de centavo con cualquier
  proveedor (RFC-0012 §1.1).

## 7. Indexación idempotente

```text
para cada fragmento:
    hash = sha256(texto_enriquecido)
    si existe chunk con (doc_id, unit, part) y content_hash == hash:  -> se omite
    si existe con hash distinto:                                      -> UPDATE + nuevo embedding
    si no existe:                                                     -> INSERT + embedding
al final:
    DELETE de los chunks de doc_id cuya (unit, part) ya no aparece en el corpus
todo dentro de una única transacción
```

> **Este RFC toca `cv_chunks`, y nada más.** El esquema de RFC-0006 trae también
> `source_documents` (el *ledger*) e `ingestion_jobs` (con `idempotency_key`, `lease_token` y
> estado), y `index_corpus()` **no escribe en ninguna de las dos**: por eso su firma en §8 no
> lleva `job_id`.
>
> El ciclo de vida del trabajo es de **RFC-0019**, que crea la entrada en `ingestion_jobs` al
> detectar que el fichero cambió y después invoca esta función. Nótese que `ingestion_jobs` tiene
> una `FOREIGN KEY ... ON DELETE RESTRICT` contra `source_documents`, así que quien cree el
> trabajo debe crear antes la fila del *ledger* — también RFC-0019.
>
> Se escribe porque RFC-0019 declara `Depende de: RFC-0002` y da por hecha esta frontera sin que
> estuviera dicha en ningún sitio. Un Desarrollador que la desconozca, o no toca las tablas y
> RFC-0019 se encuentra un hueco, o las toca dos veces.

Consecuencias buscadas:

- Reindexar sin cambios **no consume la API del proveedor de embeddings** (hoy OpenAI, RFC-0017)
  y no altera la tabla.
- Los identificadores de fragmento sobreviven a las ediciones, de modo que las conversaciones
  antiguas siguen pudiendo citar su fuente.
- La transacción única evita el estado intermedio en el que el corpus queda a medias: las
  lecturas concurrentes ven la versión anterior hasta el `COMMIT` (I-7).

## 8. Interfaz de ejecución

```bash
# CLI (DEV y QA)
python -m app.ingestion.indexer --corpus corpus/cv.md            # incremental
python -m app.ingestion.indexer --corpus corpus/cv.md --dry-run  # informe sin escribir
python -m app.ingestion.indexer --corpus corpus/cv.md --force    # re-embebe todo

# API (PROD): requiere API Key de rol admin
POST /v1/admin/reindex   {"force": false}
```

Contrato de la función principal:

```python
def index_corpus(
    corpus_path: Path,
    *,
    doc_id: str = "cv",
    force: bool = False,
    dry_run: bool = False,
) -> IngestionReport: ...

@dataclass(frozen=True)
class IngestionReport:
    inserted: int
    updated: int
    unchanged: int
    deleted: int
    embed_calls: int
    duration_ms: int
    errors: list[str]
```

En PROD, `/v1/admin/reindex` lanza la indexación como tarea en segundo plano y responde `202`
con un `job_id` consultable; no bloquea la petición.

## 9. Fallos y degradación

| Fallo | Detección | Comportamiento |
| :--- | :--- | :--- |
| Front-matter ausente o incompleto | Validador del cargador | Aborta antes de tocar la BD, código de salida 2 |
| Encabezado `###` presente | Validador | Aborta con el número de línea |
| Unidad > 400 palabras | Validador | Advertencia en `--dry-run`, error en modo normal |
| Patrón de dato sensible detectado | Validador | Aborta y señala la línea, sin volcar el valor al log |
| Error del proveedor de *embeddings* (429/5xx) | `httpx2` | Reintento; si agota, `rollback` completo. `ThrottlingException` de `boto3` ya no aplica: sin AWS (ADR-0007) |
| Corpus vacío tras el troceado | `len(chunks) == 0` | Aborta: nunca se deja la tabla vacía |

## 10. Criterios de aceptación

| # | Criterio | Verificación |
| :--- | :--- | :--- |
| CA-1 | Un `##` bajo `# Experiencia` produce exactamente un fragmento si mide ≤1 200 caracteres | `tests/unit/test_chunker.py::test_one_unit_one_chunk` |
| CA-2 | Toda cabecera de contexto contiene sección, unidad y fechas cuando existen | `test_chunker.py::test_context_header` |
| CA-3 | Una unidad de 3 000 caracteres produce sub-fragmentos con solapamiento de 120 y cabecera repetida | `test_chunker.py::test_long_unit_split` |
| CA-4 | Existe siempre un fragmento `perfil_global` | `test_chunker.py::test_global_summary_present` |
| CA-5 | Reindexar dos veces sin cambios da `inserted=0, updated=0, embed_calls=0` | `tests/integration/test_indexer.py::test_idempotent` |
| CA-6 | Eliminar una unidad del corpus la elimina de la tabla al reindexar | `test_indexer.py::test_removed_unit_is_deleted` |
| CA-7 | La ingesta corre dentro de una transacción: un fallo a mitad no deja cambios | `test_indexer.py::test_rollback_on_failure` |
| CA-8 | Los vectores almacenados tienen norma ≈1 y la dimensión del *embedder* activo (**1536**, RFC-0017; el DDL declara `VECTOR(1536)`) | `test_indexer.py::test_embedding_shape_and_norm` |
| CA-9 | El validador rechaza un corpus con `###` y uno con un teléfono personal | `tests/unit/test_corpus_validator.py` |
| CA-10 | `--dry-run` no ejecuta ningún `INSERT`/`UPDATE` ni llama a la API de *embeddings* | `test_indexer.py::test_dry_run_no_side_effects` |

## 11. Riesgos

| Riesgo | Mitigación |
| :--- | :--- |
| El corpus se escribe mal y degrada la calidad sin que nadie lo note | Validador estricto + `--dry-run` obligatorio en el PR que toque `corpus/` |
| Fragmentos demasiado homogéneos ⇒ recuperación ambigua | Cabecera de contexto con unidad y fechas, que los diferencia léxica y vectorialmente |
| Cambiar el modelo de embeddings invalida los vectores existentes | `embed_model_id` se guarda por fragmento; un cambio obliga al procedimiento de RFC-0012 §7.1 y a `--force` |
| Un fragmento largo se trunca en silencio al embeberse | Validación contra `EMBED_MAX_TOKENS` antes de la llamada (RFC-0012 §6; **no** §4.1, que describe el `TitanEmbedder` diferido por ADR-0007) |

## Contrato de auditoría (gate ADU)

| # | Comprobación | Cómo se verifica | Severidad si falla |
| :--- | :--- | :--- | :--- |
| A-1 | El texto embebido y el texto devuelto al agente son el mismo texto enriquecido | Leer `chunker.py` + `formatter.py`; prueba CA-2 | Mayor |
| A-2 | La ingesta es idempotente y no llama a la API de *embeddings* cuando nada cambió | Ejecutar CA-5 y contar llamadas al doble (ADR-0012: ninguna prueba llama a la API real) | Bloqueante |
| A-3 | Toda la ingesta ocurre en una transacción con `rollback` verificado | CA-7 | Bloqueante |
| A-4 | La ingesta llama a `embed_documents`, nunca a `embed_query` | `grep -n "embed_query" app/ingestion/` sin resultados | Bloqueante |
| A-5 | El validador aborta ante `###`, front-matter incompleto y datos sensibles | CA-9 | Mayor |
| A-6 | Existe el fragmento `perfil_global` y no duplica contenido palabra por palabra de otros | CA-4 + inspección | Menor |
| A-7 | El diccionario de sinónimos vive en `app/ingestion/synonyms.py` y es el único del repositorio | `grep` de las parejas de sinónimos fuera de ese módulo, sin resultados. **RFC-0003 lo consumirá** (punto 6 del plan): no se puede comprobar aquí que ya lo comparta, porque ese RFC no está implementado | Menor |
| A-8 | `--dry-run` no produce efectos secundarios | CA-10 | Mayor |
