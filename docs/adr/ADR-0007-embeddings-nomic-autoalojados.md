# ADR-0007 — `nomic-embed-text` autoalojado como modelo de embeddings de la PoC

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aceptada |
| **Fecha** | 2026-08-22 |
| **Modifica a** | ADR-0004 (que sigue vigente como decisión del camino AWS diferido) |
| **RFCs afectados** | RFC-0017, RFC-0012, RFC-0006, RFC-0016, RFC-0009 |

## Contexto

ADR-0004 eligió `amazon.titan-embed-text-v2:0` sobre Bedrock, y su argumento central era la
**unidad de credencial**: la generación ya corría sobre Bedrock, así que usar Titan significaba
un proveedor, una región y —en PROD— ningún secreto de API.

Ese argumento **dejó de aplicar** al aceptarse ADR-0006. Con la PoC entregándose en un VPS y sin
PROD sobre AWS, Titan ya no comparte credencial con nada: sería la *única* razón para mantener una
cuenta de AWS viva, un usuario IAM con claves rotables en el `.env` del VPS y una dependencia de
red hacia `us-east-2` en la ruta de consulta.

El propio ADR-0004 previó este momento y escribió la condición de salida:

> Se reabre si: (a) el proyecto deja de ser una PoC y la portabilidad entre nubes pasa a ser un
> requisito; (b) **se exige que el retrieval no dependa del mismo proveedor que la generación**…

Se cumple una variante más fuerte de (b): se exige que el retrieval no dependa de **ningún**
proveedor de nube. Y la salida ya estaba construida: `NomicApiEmbedder` y `OllamaEmbedder` están
implementadas y pasan la **misma suite de contrato** que Titan (RFC-0012 CA-18). Cambiar es
configuración más el procedimiento de reindexación de RFC-0012 §7.1, no código nuevo.

Queda una objeción de ADR-0004 que **no** ha caducado y que este documento tiene que responder de
frente, porque es técnica y es correcta:

> `v1.5` está entrenado sobre todo en inglés (el multilingüe es `v2-moe`), y el corpus es español.

## Decisión

Se usa **`nomic-embed-text` autoalojado en el VPS** (pesos abiertos, Apache 2.0), servido por
Ollama en la misma red del `docker compose`, detrás de la interfaz `Embedder` ya existente. La
dimensión pasa de **1024 a 768**, lo que obliga a recrear la columna y reindexar (RFC-0012 §7.1).

**La variante concreta se decide por evaluación, no por preferencia.** Es un requisito de esta
decisión, no una tarea opcional:

1. Se indexa el corpus y se corre el conjunto dorado de RFC-0009 con **`nomic-embed-text-v1.5`**.
2. Se repite con la variante **multilingüe (`v2-moe`)** por la vía de servicio que resulte estar
   disponible en el entorno.
3. Gana la que alcance **Context recall ≥ 0.85** (umbral de merge de RFC-0009 §4), que es
   determinista y no usa juez LLM. Si ambas lo alcanzan, gana la de menor huella de memoria.
4. Si **ninguna** lo alcanza, la decisión falla y se escala al Arquitecto: la salida documentada
   es volver a un embedder multilingüe por API, no bajar el umbral.

Se declara explícitamente lo que **no** se sabe hoy: qué variantes de Nomic sirve la versión de
Ollama que se instale en el VPS. Es una comprobación de entorno, no una decisión de arquitectura,
y por eso vive como criterio de aceptación verificable (RFC-0017) en vez de como una afirmación
de este documento. El corpus es español; elegir a ciegas la variante entrenada en inglés porque
es la que trae el nombre de modelo más corto sería exactamente el error que ADR-0004 anticipó.

La generación **no** cambia en este ADR: se decide aparte, en ADR-0008. Cambiar embedder y
generador a la vez haría que una caída de calidad fuera imposible de atribuir.

## Alternativas consideradas

| Alternativa | A favor | En contra | Por qué se descarta |
| :--- | :--- | :--- | :--- |
| **Nomic autoalojado (Ollama en el VPS)** | Cero credenciales de terceros y cero dependencia de nube: coherente con ADR-0006. Coste cero. Sin límite de tasa por IP. Pesos abiertos: el mismo modelo en DEV y en QA. Ya implementado y cubierto por la suite de contrato (CA-18) | Consume memoria del VPS, que pasa a ser requisito de arquitectura. Ollama **no** aplica los prefijos `search_document:` / `search_query:`: los pone `OllamaEmbedder` a mano (CA-17), y equivocarlos degrada la calidad **sin producir ningún error** | **Elegida** |
| Nomic Embedding API | Sin memoria en el VPS. Acepta lote. Acceso directo a la variante multilingüe | Reintroduce una credencial de larga vida (`NOMIC_API_KEY`) y un tercero en la ruta de consulta. **Límite de tasa por IP**, y el VPS y los runners de CI comparten IP saliente | Contradice el motivo de ADR-0006: quitar dependencias de servicios gestionados. Queda como contingencia si la evaluación tumba las dos variantes locales |
| Mantener Titan V2 desde el VPS | Cero cambios: ni dimensión, ni reindexación, ni DDL. Multilingüe por diseño | Obliga a sostener una cuenta de AWS, un usuario IAM con claves en el `.env` y su rotación a 90 días **solo** para embeddings. Deja la ruta de consulta atada a `us-east-2` | Sostener toda la superficie de AWS para un componente que cuesta fracciones de centavo es justo lo que ADR-0006 vino a eliminar |
| `sentence-transformers` embebido en la imagen | Sin red y sin servicio auxiliar en la ruta de consulta | `torch` + pesos ⇒ imagen ~1.1 GB frente a ~180 MB, y arranque en frío de 8–12 s | Rompe el empaquetado de RFC-0015 y el arranque de ~2 s, a cambio de evitar un salto de red dentro del mismo host |
| OpenAI `text-embedding-3-small` | Buena calidad multilingüe, barato | Otro proveedor propietario, otra clave, y vuelve a atar el retrieval a un servicio gestionado | No aporta nada que Nomic no dé, y reintroduce lo que se quiere quitar |

## Consecuencias

**Positivas**

- **La aplicación deja de necesitar credenciales de AWS.** Junto con ADR-0008, se retira el
  usuario IAM `rag-cv-qa-invoker`, sus claves del `.env` del VPS y su rotación (RFC-0007 §5.2).
- **Pesos abiertos**: el modelo se puede fijar por *digest* y no cambia bajo los pies. Con Titan,
  un cambio del proveedor produce *otro* modelo y obliga a reindexar sin aviso.
- **Desarrollo offline real.** DEV deja de necesitar red y credenciales para indexar y consultar,
  que era la contrapartida declarada en RFC-0012 §6.
- **Coste cero** y sin límite de tasa por IP.
- **RNF-12 se cumple mejor que antes**: DEV y QA corren el mismo modelo con el mismo *digest*, y
  no hay dos caminos de servicio distintos. La divergencia F16 vs canónico que ADR-0004 temía
  aparecía al mezclar Ollama local con API remota; aquí no se mezcla.

**Negativas / deuda aceptada**

- **Reindexación obligatoria y cambio de esquema**: `VECTOR(1024)` → `VECTOR(768)`, con
  recreación del índice HNSW. El DDL vigente lo fija en `infra/sql/001_initialize_rag_cv.sql` y en
  RFC-0006 §DDL. No es una migración de columna: los vectores existentes dejan de ser comparables.
- **El VPS necesita memoria para el modelo.** Deja de ser un detalle de compra y pasa a ser
  requisito con número (RFC-0016 §5).
- **Un servicio más en el `docker compose`**, con su arranque, su *health check* y su fallo
  propio. El primer *pull* del modelo es un paso de aprovisionamiento que hay que hacer explícito
  o el primer despliegue falla de forma confusa.
- **Riesgo de calidad en español no resuelto de antemano**, sino sometido a evaluación. Es la
  deuda honesta de esta decisión: se acepta arrancar sin saber la respuesta, con un umbral fijado
  y una salida documentada si no se alcanza.
- **La asimetría del modelo pasa a ser real.** Con Titan (simétrico) los dos métodos de la
  interfaz eran redundantes; con Nomic, usar el prefijo equivocado degrada la recuperación **sin
  error visible**. Es exactamente el escenario que RFC-0012 §3 anticipó al negarse a colapsar
  `embed_documents` y `embed_query` en un `embed()` genérico — esa decisión, que parecía
  sobreingeniería, es hoy lo que hace este cambio barato y seguro.

## Condición de revisión

Se reabre si: (a) ninguna variante de Nomic alcanza el umbral de *context recall* de RFC-0009;
(b) la memoria del VPS resulta insuficiente para sostener el modelo junto al resto de servicios;
o (c) el proyecto vuelve a AWS (ADR-0006), momento en el que ADR-0004 recupera su vigencia
completa sin necesidad de reescribirse.
