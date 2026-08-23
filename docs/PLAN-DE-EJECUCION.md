# Plan de ejecución — orden de implementación de la PoC

**Alcance vigente:** la PoC se entrega en **QA, un VPS Ubuntu**, con despliegue **nativo por SSH**.
**AWS queda diferido**, no cancelado (ADR-0006, ADR-0010).

Este documento responde a una sola pregunta: **en qué orden se implementan los RFCs y qué hay que
leer junto a cada uno.** No redefine nada.

| Pregunta | Documento que manda |
| :--- | :--- |
| ¿Qué está vigente, con delta o diferido? | [RFC-0016 §3](rfc/RFC-0016-alcance-poc-y-entrega-en-qa.md) |
| ¿Cómo se ejecuta un RFC? | [ADU-PROCESO](adu/ADU-PROCESO.md) y [RFC-0014](rfc/RFC-0014-disciplina-tdd.md) |
| ¿En qué orden? | **Este documento** |

> **Supersede la hoja de ruta anterior** ([`diagramas/hoja-de-ruta.md`](diagramas/hoja-de-ruta.md)
> y `README.md#hoja-de-ruta`) para el alcance vigente. Aquella termina en «desplegar la
> arquitectura PROD en AWS»; esta termina en QA. Aquella no se borra: recupera vigencia si se
> cierra ADR-0006.

---

## 1. Punto de partida

El repositorio contiene **documentación, el DDL de bootstrap y el workflow de CI que lo verifica**.
No hay una sola línea de Python. Todo lo que sigue está por construir.

## 2. Orden de ejecución

Una rama y un PR por RFC (ADU-PROCESO §9): `feat/rfc-000N-<slug>`.

### Fase 0 — Fundaciones · *hacer posible el TDD*

| # | RFC | Produce | Deltas obligatorios que leer junto al RFC |
| :--- | :--- | :--- | :--- |
| 1 | **RFC-0011** Entorno DEV Windows | Python 3.12, PostgreSQL 16 + pgvector nativo, base con ICU `es-MX`, bootstrap idempotente, tareas `invoke`, `TEST_DB_MODE=local` | **CA-0 derogado**: exige comprobar acceso a Bedrock y no hay AWS. Se sustituye por comprobar `OPENAI_API_KEY`. **DEV sigue necesitando red**: el embedder es por API (RFC-0016 §3.1) |
| 2 | **RFC-0006** Modelo de datos | Extensiones, DDL, índices, restricciones, migraciones Alembic, pooling, comprobaciones de arranque | `VECTOR(1024)` → **`VECTOR(1536)`** (RFC-0017 §4). Semántica del ledger sin S3: `s3_version_id` = **ULID de la detección**, `s3_etag` = huella `mtime+size` (RFC-0016 §3.3) |

Sin la fase 0 no se puede entregar un test en rojo, y el commit rojo es la evidencia de que hubo
TDD (RFC-0014 §6). Es la razón de que el esquema no vaya primero.

### Fase 1 — Ingesta · *el CV indexado y vigilándose solo*

| # | RFC | Produce | Deltas obligatorios que leer junto al RFC |
| :--- | :--- | :--- | :--- |
| 3 | **RFC-0012 + RFC-0017** Embeddings | Interfaz `Embedder`, fábrica, suite de contrato parametrizada, `FakeEmbedder` y `OpenAIEmbedder` | **Solo esas dos implementaciones.** Titan, Nomic y Ollama quedan diferidas con su camino (RFC-0017 §1). Dimensión **1536**; el `openai_compatible` de RFC-0013 **no** da embeddings |
| 4 | **RFC-0002** Ingesta y chunking | Formato del corpus, normalización, troceado por unidad `##`, enriquecimiento de contexto, indexación idempotente, CLI | La fuente es **fichero local en el VPS**, no S3 (RFC-0016 §3.3). El corpus **no se versiona en Git** |
| 5 | **RFC-0019** Sondeo del corpus | `cron` de usuario, comprobación de estabilidad, *lease*, latido y alerta por ausencia | Sustituye el disparador por eventos de S3. **Reversión ⇒ regenerar embeddings** (§6) |

**Al cerrar la fase 1 hay algo demostrable:** el CV indexado en PostgreSQL, reindexándose solo
cuando el archivo cambia.

### Fase 2 — Respuestas · *el agente contesta*

| # | RFC | Produce | Deltas obligatorios que leer junto al RFC |
| :--- | :--- | :--- | :--- |
| 6 | **RFC-0003** Recuperación híbrida | HNSW + PostgreSQL FTS + fusión RRF, degradación a rama léxica | La degradación cubre ahora la caída del **proveedor de embeddings** |
| 7 | **RFC-0013 + RFC-0018** Proveedores LLM | Fábrica `build_model`, validación por rama, `PROVEEDOR=anthropic` con `claude-haiku-4-5` | Valor por defecto `bedrock` **sustituido**. RFC-0007 §5.2 (usuario IAM en QA) **derogado** |
| 8 | **RFC-0004** Capa de agente | Agente Strands, prompt de sistema versionado, herramienta de recuperación | La construcción del modelo la delega en RFC-0013 |
| 9 | **RFC-0005** API REST | Contrato HTTP, autenticación por API Key, límite de tasa, `/healthz` y `/readyz` | `/readyz` **expone el SHA de commit desplegado** (RFC-0020 §6, CA-5) |

### Fase 3 — Calidad · *el gate que decide si funciona*

| # | RFC | Produce | Deltas obligatorios que leer junto al RFC |
| :--- | :--- | :--- | :--- |
| 10 | **RFC-0009** Evaluación y guardrails | Conjunto dorado, métricas, umbrales de merge, suite adversarial, calibración del juez | **Sin cambios: los umbrales no se relajan.** Verifica *Context recall* ≥ 0.85 (RFC-0017 §3). Juez y agente comparten proveedor: la calibración de 15 casos decide si sirve (RFC-0018 §5) |

**RFC-0014 (TDD) es transversal**, no una fase: aplica desde el punto 1. Sus comprobaciones de
§6 —commit rojo, orden test → implementación, reversión pone el test en rojo— se auditan en cada
PR.

### Fase 4 — Entrega en QA

| # | RFC | Produce | Deltas obligatorios que leer junto al RFC |
| :--- | :--- | :--- | :--- |
| 11 | **RFC-0020** Topología nativa (nginx, no Caddy) | Aprovisionamiento, unidad `systemd` de usuario, `enable-linger`, despliegue `rsync` + enlace `current`, reversión, **endurecimiento de la unidad (§5.1)** | Sustituye RFC-0007 §5.1 y §5.3 y RFC-0015 §7. **Excluir `.env` y `corpus/` del `rsync`**. §5.1 recupera las diez medidas de endurecimiento que se perdieron al diferir RFC-0015 |
| 12 | **RFC-0008** CI/CD | Pipeline de calidad, construcción y despliegue **hasta QA** | El paso de promoción a PROD por *digest* y la deriva de Terraform **no aplican** |
| 13 | **RFC-0010** Observabilidad | Logs JSON con rotación, métricas, alertas, runbook | CloudWatch y las diez alarmas de §6 **diferidas**. El runbook incorpora el reemplazo atómico del corpus (RFC-0019 §4) y la reindexación (§9.6c) |

Tras la fase 4 se re-ejecuta la evaluación **contra QA**, que es lo que exige RFC-0016 CA-5.

## 3. Qué NO se implementa

| Documento | Motivo |
| :--- | :--- |
| RFC-0007 §6, §7, §9, §10 | PROD, IAM de AWS, Terraform y costos de AWS — diferidos (ADR-0006) |
| RFC-0015 completo | Empaquetado en contenedor; el VPS no usa contenedores (ADR-0010). **Su §10 sí se ejecuta**, traducida a directivas de `systemd` en RFC-0020 §5.1 |
| Ingesta por eventos de S3, worker, DLQ y reconciliación | Sustituidos por el sondeo (ADR-0009) |
| `TitanEmbedder`, `NomicApiEmbedder`, `OllamaEmbedder` | Camino AWS diferido y contingencias sin host que las sostenga (ADR-0007) |
| RFC-0001 | Es el mapa del sistema, no un entregable. Se lee, no se implementa |

**Diferido no es obsoleto.** Ninguno de esos documentos se edita, y todos recuperan vigencia si se
cierra ADR-0006.

## 4. Cómo se ejecuta cada RFC

1. **Gate G2 — Definition of Ready.** El Desarrollador comprueba los siete puntos de ADU-PROCESO
   §4 **más los deltas de la tabla**. Si falta uno, **rechaza el RFC y lo devuelve**. Eso también
   es trabajo.
2. **Handoff** con el formato de ADU-PROCESO §8, junto al prompt del Desarrollador pegado tal cual.
3. **Commit de tests EN ROJO**, en su propio commit. Sin él, hallazgo **Mayor** del Auditor. El
   rojo debe fallar por la razón correcta: un `ImportError` no demuestra nada.
4. **Implementación** hasta verde, criterio por criterio, sin aplastar el historial.
5. **Gate G3 — Definition of Done** (ADU-PROCESO §5) e Informe de Implementación con el mapa
   criterio → test y las desviaciones declaradas. Una desviación no declarada es **Bloqueante**.
6. **Gate G4 — Auditoría** contra el contrato del RFC. La lista es cerrada.

## 5. Definición de terminado para la PoC

- El agente responde sobre el CV en `https://reto.qrimapp.com`, fundamentado y citando fragmentos.
- Se abstiene correctamente cuando la respuesta no está en el corpus.
- Actualizar `cv.md` en el VPS reindexa solo, y se puede demostrar.
- La suite de RFC-0009 corre contra QA y publica sus métricas.
- **RNF-4, RNF-6 y RNF-10 constan como `no verificados`**, no como cumplidos (RFC-0016 §6, CA-7).

## 6. Bloqueos que dependen del dueño del producto

| Bloqueo | Bloquea a |
| :--- | :--- |
| Mergear el PR de los contratos | Todo: sin gate G1 no hay RFC aprobado que tomar |
| `OPENAI_API_KEY` | Verificar CA-0' de RFC-0011 y toda la fase 1 |
| `ANTHROPIC_API_KEY` | Fase 2, punto 7 |
| ~~Dominio~~ **resuelto**: `reto.qrimapp.com`, servido por el nginx que ya corre en el VPS | — |
| Respuestas de las preguntas frecuentes del corpus | No bloquea, pero el agente se abstendrá en disponibilidad, modalidad y expectativas de rol |
