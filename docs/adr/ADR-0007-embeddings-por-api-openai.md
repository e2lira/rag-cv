# ADR-0007 — `text-embedding-3-small` de OpenAI como modelo de embeddings de la PoC

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aceptada |
| **Fecha** | 2026-08-22 |
| **Modifica a** | ADR-0004 (que sigue vigente como decisión del camino AWS diferido) |
| **RFCs afectados** | RFC-0017, RFC-0012, RFC-0006, RFC-0016, RFC-0020, RFC-0009 |

## Contexto

ADR-0004 eligió `amazon.titan-embed-text-v2:0` sobre Bedrock, y su argumento central era la
**unidad de credencial**: la generación ya corría sobre Bedrock, así que Titan significaba un
proveedor, una región y —en PROD— ningún secreto de API.

Ese argumento **dejó de aplicar** al aceptarse ADR-0006. Sin PROD sobre AWS, Titan sería la
*única* razón para mantener una cuenta de AWS viva, un usuario IAM con claves rotables y una
dependencia de red hacia `us-east-2` en la ruta de consulta.

El propio ADR-0004 previó este momento:

> Se reabre si: (a) el proyecto deja de ser una PoC y la portabilidad entre nubes pasa a ser un
> requisito; (b) **se exige que el retrieval no dependa del mismo proveedor que la generación**…

Se cumple una variante más fuerte de (b): se exige que no dependa de **AWS**.

La salida natural parecía autoalojar `nomic-embed-text`: pesos abiertos, coste cero, sin
credenciales. **El VPS no tiene capacidad de cómputo para sostener la inferencia local.** No es
una sorpresa: RFC-0016 §5 ya había identificado que el recurso escaso del host son los **2
núcleos**, compartidos por PostgreSQL, la API y el sondeo, y que embeber dejaría de ser una espera
de red para convertirse en cómputo compitiendo con la generación de respuestas.

Así que la elección real no es "autoalojado o API", sino **qué API**.

## Decisión

Se usa **`text-embedding-3-small` de OpenAI, a sus 1536 dimensiones nativas**, detrás de la
interfaz `Embedder` ya existente.

**A 1536 y no truncado a 768.** El modelo admite acortar la salida con el parámetro `dimensions`,
y la tentación es usarlo para no tocar el DDL. Es un ahorro falso: **el DDL cambia igual**, porque
hoy declara `vector(1024)` (Titan V2). Migrar de 1024 a 1536 cuesta exactamente lo mismo que de
1024 a 768, y truncar solo entregaría menos información por vector. Con un corpus de ~60
fragmentos, lo que se ahorraría en índice es irrelevante.

La calidad en español —la objeción que ADR-0004 levantó contra Nomic `v1.5`, entrenado sobre todo
en inglés— **sigue decidiéndose midiendo, no por preferencia**: el procedimiento de RFC-0017 §3
exige alcanzar *Context recall* ≥ 0.85 sobre el conjunto dorado de RFC-0009, que es determinista y
no usa juez LLM. Si no se alcanza, la decisión escala al Arquitecto y **no se baja el umbral**.

La generación **no** cambia aquí: sigue siendo `claude-haiku-4-5` por la API de Anthropic
(ADR-0008). Cambiar embedder y generador a la vez haría una caída de calidad inatribuible.

## Alternativas consideradas

| Alternativa | A favor | En contra | Por qué se descarta |
| :--- | :--- | :--- | :--- |
| **`text-embedding-3-small` a 1536** | Multilingüe sólido, que responde de frente la objeción de ADR-0004 sobre un corpus en español. Cuotas **por clave**, no por IP. Acepta lote en una sola llamada, a diferencia de Titan. Coste de céntimos. Modelo simétrico: sin prefijos que aplicar mal en silencio | Exige una implementación nueva —`OpenAIEmbedder`— y su rama en la fábrica; no hay atajo de configuración. Pesos cerrados: si el modelo cambia o se retira, la salida es *otro* modelo y hay que reindexar. Segundo secreto de larga vida en el VPS | **Elegida** |
| Nomic API (`nomic-embed-text-v2-moe`) | **Cero código nuevo**: `NomicApiEmbedder` ya está implementado y pasa la suite de contrato (RFC-0012 CA-18). 768 dim. Pesos abiertos: el día que hubiera cómputo, se autoaloja **el mismo modelo** sin reindexar | **Límite de tasa por IP**, que ADR-0004 ya señaló como problema real: las corridas de evaluación hacen muchas llamadas y los ejecutores de CI comparten IP de salida. Una evaluación estrangulada a mitad no es un fallo claro, es ruido | Su ventaja —cero código— es real y pesa; la pierde frente al riesgo de que el gate de calidad se vuelva intermitente por una cuota compartida |
| Autoalojar `nomic-embed-text` con Ollama | Coste cero, sin credenciales, desarrollo offline | **El VPS no tiene cómputo para sostenerlo.** Y aunque lo tuviera, embeber pasaría a competir por 2 núcleos con la generación (RFC-0016 §5) | La restricción es del host, no del diseño |
| Mantener Titan V2 desde el VPS | Cero cambios: ni dimensión, ni reindexación, ni DDL | Obliga a sostener cuenta de AWS, usuario IAM y rotación de claves **solo** para embeddings | Es exactamente la dependencia que ADR-0006 vino a eliminar |
| `text-embedding-3-large` | Mejor calidad medida | 3072 dimensiones y varias veces el coste, para un corpus de 20 000 tokens donde el cuello de botella no es el embedding | Paga capacidad que este problema no usa. Reconsiderable solo si `3-small` no alcanza el umbral de RFC-0017 §3 |
| `sentence-transformers` dentro del proceso de la API | Sin salto de red en la ruta de consulta | `torch` + pesos ⇒ ~1.1 GB de dependencias y arranque en frío de 8–12 s, en el host que precisamente no tiene cómputo | Misma restricción que Ollama, con peor arranque |

## Consecuencias

**Positivas**

- **La aplicación deja de necesitar credenciales de AWS.** Junto con ADR-0008, se retira el usuario
  IAM `rag-cv-qa-invoker`, sus claves y su rotación (RFC-0007 §5.2).
- **El VPS deja de necesitar cómputo de inferencia.** Desaparece el proceso de Ollama, su unidad de
  `systemd`, su memoria y su competencia por los 2 núcleos. RFC-0016 §5 vuelve a un dimensionado
  holgado.
- **Embebido en lote.** `/v1/embeddings` acepta un array, a diferencia de Titan, que exigía una
  llamada por texto y concurrencia acotada para no chocar con la cuota.
- **Cuotas por clave, no por IP.** Las corridas de evaluación dejan de competir con lo que haga
  cualquier otro inquilino de la misma IP de salida.
- **Modelo simétrico.** Sin los prefijos `search_document:` / `search_query:` que en Nomic degradan
  la recuperación **sin producir ningún error** si se aplican al lado equivocado.
- **Embedder y generador son de proveedores distintos.** Una caída de uno no se lleva al otro, que
  es justo lo que fallaba en el diseño original con Bedrock para ambos.

**Negativas / deuda aceptada**

- **Implementación nueva.** `OpenAIEmbedder` y su rama en la fábrica no existen: la fábrica solo
  tiene `titan | fake | nomic_api | ollama`. Es la ventaja concreta que se renuncia frente a Nomic
  API. Queda acotada porque la suite de contrato de RFC-0012 (CA-18) ya existe y solo gana una
  quinta implementación. **Cuidado con una confusión fácil:** el `openai_compatible` de RFC-0013
  es la rama de **generación**; no aporta embeddings.
- **Pesos cerrados, otra vez.** Es la misma objeción que ADR-0004 levantó contra Titan y no
  desaparece por cambiar de proveedor: si el modelo cambia o se retira, la salida es *otro* modelo
  y hay que reindexar. Se acota fijando el identificador exacto y persistiendo `embed_model_id`
  por fragmento (RFC-0017 §5).
- **Se pierde el desarrollo offline.** DEV vuelve a necesitar red y una credencial para indexar y
  consultar. Es la contrapartida que el autoalojamiento habría devuelto y que esta decisión
  entrega de nuevo.
- **Segundo secreto de larga vida** en el VPS: `OPENAI_API_KEY` junto a `ANTHROPIC_API_KEY`. Y sin
  usuario de servicio sin shell (RFC-0016 §8.1), quien entre por SSH con la cuenta de operación lee
  ambos.
- **Dos dependencias externas en la ruta de consulta**, no una. Son independientes —una caída de
  OpenAI no afecta a Anthropic— pero la superficie de indisponibilidad es mayor. La degradación a
  rama léxica de RFC-0003 §6 cubre la caída del embedder.
- **Coste por token en embeddings**, antes cero con el plan autoalojado. Son céntimos con este
  corpus, pero deja de ser estrictamente nulo.

## Condición de revisión

Se reabre si: (a) `text-embedding-3-small` no alcanza el umbral de *context recall* de RFC-0017
§3, en cuyo caso el siguiente candidato documentado es `text-embedding-3-large`; (b) el VPS gana
capacidad de cómputo y el autoalojamiento vuelve a ser viable, donde Nomic recupera su ventaja de
pesos abiertos; (c) aparece un requisito de residencia de datos que impida enviar el corpus a un
tercero; o (d) el proyecto vuelve a AWS (ADR-0006), donde ADR-0004 recupera su vigencia completa
sin reescribirse.
