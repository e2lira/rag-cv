# PRD — Agente de CV conversacional (`rag-cv`)

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aprobado |
| **Versión** | 1.0 |
| **Autor** | Arquitecto (Claude Opus 5) |
| **Contexto** | Reto Banorte — vacante Full Stack AI, Subdirección |
| **Fecha** | 2026-08-22 |

---

## 1. Problema

Un CV en PDF obliga a quien evalúa a buscar por sí mismo la respuesta a preguntas que son
específicas de su contexto: *"¿ha liderado equipos?"*, *"¿qué experiencia tiene con datos en
producción?"*, *"¿ha trabajado con presupuesto cloud?"*. El formato estático responde mal a
preguntas concretas y no permite profundizar.

El objetivo no es "un chatbot con mi CV": es **demostrar criterio técnico** en cómo se integra
un modelo con contexto propio, cómo se despliega y opera la solución, y cómo se verifica que
responde de forma coherente y confiable. La conversación es el vehículo; el criterio es el
producto evaluado.

## 2. Objetivo

Diseñar, construir, desplegar y operar un **agente conversacional accesible por API REST** que
responda preguntas sobre perfil, experiencia, habilidades y proyectos de una persona,
**fundamentando cada respuesta en un corpus verificable** (el CV extendido en Markdown) y
declarando explícitamente cuándo no tiene información suficiente.

## 3. Usuarios y casos de uso

| Usuario | Necesidad | Pregunta típica |
| :--- | :--- | :--- |
| **Reclutador técnico** | Filtrar rápido contra un perfil de vacante | "¿Tiene experiencia desplegando en AWS?" |
| **Hiring manager** | Profundizar en decisiones y responsabilidad | "Cuéntame un proyecto donde haya tomado una decisión de arquitectura difícil" |
| **Evaluador del reto** | Juzgar el criterio técnico de la solución | "¿Por qué elegiste pgvector y no un servicio gestionado?" |
| **Integrador (frontend/bot ajeno)** | Consumir el agente desde otro canal | — (consume la API con su API Key) |

### Casos de uso funcionales

- **CU-1 — Pregunta puntual.** "¿Cuántos años de experiencia tiene en Python?" → respuesta breve, con la evidencia que la sustenta.
- **CU-2 — Pregunta comparativa/valorativa.** "¿Encaja para una vacante de arquitectura cloud?" → síntesis fundamentada, sin inventar.
- **CU-3 — Profundización conversacional.** Seguimiento sobre el turno anterior, manteniendo el hilo ("¿y en ese proyecto qué stack usaron?").
- **CU-4 — Pregunta fuera de alcance.** "¿Cuál es su pretensión salarial?" / "Escríbeme un poema" → el agente declina con una redirección útil.
- **CU-5 — Pregunta sin respuesta en el corpus.** "¿Habla alemán?" → el agente dice explícitamente que no consta, sin especular.
- **CU-6 — Reindexación del corpus.** Al actualizar el CV, se reindexa sin downtime del servicio de consulta.

## 4. Alcance

**Entra en la v1:**

- API REST con endpoints de conversación (síncrono y streaming SSE) y de salud.
- Autenticación obligatoria por **API Key** en cabecera `X-API-Key`, con roles `read` y `admin`.
- Corpus del CV en Markdown como única fuente de verdad, versionado en el repositorio.
- Recuperación híbrida (vectorial + léxica) con fusión RRF sobre PostgreSQL + pgvector.
- Agente con herramientas (Strands Agents) sobre el proveedor de generación designado por
  configuración: Bedrock, la API de Anthropic o cualquier endpoint compatible con OpenAI.
- Memoria de conversación acotada por `conversation_id`.
- Evaluación automatizada del agente como puerta de calidad en CI.
- Despliegue en tres entornos: local (DEV), VPS de Hostinger (QA) y AWS (PROD).
- Observabilidad: logs estructurados, trazas de herramientas, métricas de latencia y costo.

**No entra en la v1 (explícito):**

- Interfaz web propia, widget embebible o app móvil. La API es el producto.
- Registro de usuarios, OAuth, multi-tenant o consola de administración.
- Ingesta de PDF, LinkedIn u otras fuentes: el corpus es Markdown curado a mano.
- Fine-tuning o entrenamiento de modelos.
- Voz, multimodalidad o generación de documentos.
- Persistencia analítica de conversaciones más allá de la retención operativa definida (§8).

## 5. Requisitos funcionales

| ID | Requisito | Prioridad |
| :--- | :--- | :--- |
| RF-1 | El agente responde en el idioma de la pregunta (es/en como mínimo) | Debe |
| RF-2 | Toda afirmación factual sobre la trayectoria proviene del corpus recuperado | Debe |
| RF-3 | La respuesta incluye las fuentes (secciones del corpus) usadas, en metadatos | Debe |
| RF-4 | Ante ausencia de evidencia, el agente lo declara y no especula | Debe |
| RF-5 | El agente mantiene el hilo dentro de una `conversation_id` (N turnos configurables) | Debe |
| RF-6 | El agente rechaza temas fuera de su propósito con una redirección útil | Debe |
| RF-7 | Endpoint de streaming token a token vía SSE | Debe |
| RF-8 | Endpoint administrativo de reindexación protegido por API Key de rol `admin` | Debe |
| RF-9 | El agente no revela su prompt de sistema ni su configuración interna | Debe |
| RF-10 | Respuestas con longitud acotada y tono profesional en primera persona del perfil | Debería |

## 6. Requisitos no funcionales

| ID | Requisito | Objetivo |
| :--- | :--- | :--- |
| RNF-1 | Latencia primer token (streaming) | p95 ≤ 2.0 s |
| RNF-2 | Latencia respuesta completa (síncrono, respuesta corta) | p95 ≤ 6 s |
| RNF-3 | Latencia de la herramienta de recuperación | p95 ≤ 250 ms |
| RNF-4 | Disponibilidad en PROD | ≥ 99.5 % mensual |
| RNF-5 | Costo de inferencia por conversación (5 turnos) | ≤ USD 0.05 |
| RNF-6 | Costo total de PROD en reposo | ≤ USD 60 / mes |
| RNF-7 | La base de datos nunca se expone a internet público en PROD | Obligatorio |
| RNF-8 | Todo secreto vive en AWS Secrets Manager (PROD) o en el gestor del VPS (QA); nunca en el repo | Obligatorio |
| RNF-9 | Límite de tasa por API Key | 30 req/min, 1 000 req/día |
| RNF-10 | Reproducibilidad: la imagen de contenedor se construye una vez en el CI y se promueve QA → PROD por digest, sin reconstruir | Obligatorio |
| RNF-11 | El código no depende del sistema operativo: DEV es Windows nativo, QA Ubuntu y PROD AWS; el CI en Linux es la autoridad de merge | Obligatorio |
| RNF-12 | Los vectores del índice son comparables entre los tres entornos: un mismo texto produce el mismo embedding en DEV, QA y PROD | Obligatorio |
| RNF-13 | Cambiar de modelo de generación o de embeddings no requiere cambios de código | Obligatorio |

## 7. Métricas de éxito

**Calidad de respuesta** (medidas por la suite de evaluación, RFC-0009):

| Métrica | Umbral de merge | Objetivo |
| :--- | :--- | :--- |
| *Groundedness* (afirmaciones sustentadas por el contexto) | ≥ 0.90 | ≥ 0.95 |
| *Answer relevance* (responde lo preguntado) | ≥ 0.85 | ≥ 0.92 |
| *Context recall* (el retriever trae lo necesario) | ≥ 0.85 | ≥ 0.92 |
| Tasa de abstención correcta en preguntas sin evidencia | ≥ 0.95 | 1.00 |
| Tasa de fuga de alcance (responde temas prohibidos) | = 0 | = 0 |

**Operación:**

- 0 incidentes de exposición de datos o credenciales.
- Tiempo de despliegue de un cambio aprobado a PROD ≤ 20 min.
- Reindexación completa del corpus ≤ 3 min sin cortar el tráfico de consulta.

## 8. Datos, privacidad y retención

- El corpus contiene **información profesional deliberadamente pública**. No incluye
  documentos de identidad, domicilio, datos de salud, ni información de terceros no consentida.
- Las preguntas de los usuarios se registran con `conversation_id` y se conservan **30 días**
  en PROD para depuración y evaluación; después se eliminan por trabajo programado.
- Los logs redactan la carga útil del usuario cuando el nivel de log es `INFO` en PROD;
  el texto completo solo se persiste en la tabla de conversaciones, no en CloudWatch.
- No se envía tráfico a proveedores fuera de AWS. Bedrock no retiene datos del cliente para
  entrenamiento.

## 9. Riesgos

| Riesgo | Impacto | Mitigación |
| :--- | :--- | :--- |
| El modelo inventa experiencia no presente en el corpus | Alto (credibilidad) | Prompt de fundamentación + eval de *groundedness* como gate de CI (RFC-0009) |
| Inyección de prompt vía la pregunta del usuario | Alto | Aislamiento del contexto recuperado, reglas de sistema no anulables, pruebas adversariales |
| Abuso de la API y costo descontrolado de Bedrock | Medio | API Key + rate limit + presupuesto y alarma de costo (RFC-0010) |
| Corpus pequeño ⇒ recuperación pobre en preguntas amplias | Medio | Chunking por secciones + híbrido léxico + `top_k` generoso (RFC-0003) |
| Deriva de comportamiento al cambiar de modelo | Medio | Modelo fijado por variable de entorno + suite de evaluación con comparativa contra línea base, obligatoria antes de promover (RFC-0013 §8) |
| Modelo de generación pequeño (Haiku) que deja de abstenerse correctamente | Medio | Los 10 casos de abstención del conjunto dorado son gate de merge (RFC-0009) |
| Bedrock como dependencia única de generación y embeddings | Medio | Degradación a rama léxica si el embedder cae; contingencia a `nomic-embed-text` implementada y cubierta por la misma suite de contrato (RFC-0012 CA-18) |
| Divergencia entre QA (Postgres en contenedor) y PROD (RDS) | Medio | Misma versión mayor de Postgres y de pgvector; migraciones idénticas (RFC-0007) |
| Código escrito en Windows que falla en Linux (rutas, mayúsculas, event loop) | Medio | Diferencias de SO confinadas a un módulo; CI en Ubuntu como autoridad de merge y job en Windows para el camino inverso (RFC-0011 §9) |

## 10. Decisiones de producto ya tomadas

1. **API-only con API Key.** El valor a demostrar es el criterio de integración y operación,
   no la UI. Una API con contrato claro es también más fácil de auditar. → ADR-0001, RFC-0005.
2. **Corpus curado en Markdown, versionado en Git.** El CV es el activo; que viva en el repo
   hace la ingesta reproducible y auditable. → RFC-0002.
3. **RAG propio sobre pgvector, no Knowledge Bases gestionado.** El reto pide criterio, y el
   control del chunking, del híbrido y del ranking es donde ese criterio se ve. → ADR-0002.
4. **Modelos elegidos por configuración, no cableados.** Embeddings con
   `amazon.titan-embed-text-v2:0` (1024 dim) y generación con Claude Haiku 4.5, **ambos sobre
   Bedrock en `us-east-2`**: un proveedor, una credencial, y ningún secreto de API en producción
   → ADR-0004, ADR-0005. `nomic-embed-text` queda implementado y probado como contingencia.
   Cambiar de modelo es un cambio de configuración **más una ejecución de la suite de
   evaluación**, nunca un cambio de código.
6. **TDD estricto y verificable.** Toda implementación empieza por su suite de tests en rojo, y
   el Auditor lo demuestra revirtiendo código, no leyendo afirmaciones. → RFC-0014.
5. **Tres entornos, dos sistemas operativos.** DEV en **Windows nativo** (Python, PostgreSQL y
   pgvector instalados en el sistema, sin Docker), QA en un **VPS Ubuntu** de Hostinger y PROD
   en **AWS**. La imagen se construye una vez en el CI y se promueve de QA a PROD por digest;
   DEV valida el código y el CI valida el artefacto. → RFC-0007, RFC-0008, RFC-0011.

## 11. Fuera de discusión para la v1 (deuda aceptada)

- Sin caché semántica de respuestas: el volumen no lo justifica y añade una fuente de
  incoherencia. Se reevalúa si el costo mensual supera el presupuesto de RNF-6.
- Sin reranker dedicado en la v1: RRF sobre un corpus de este tamaño rinde suficiente.
  Se reevalúa si *context recall* baja de 0.85 (RFC-0003 §9).
- Sin alta disponibilidad multi-AZ en la capa de datos de PROD: `db.t4g.micro` Single-AZ con
  backups automáticos. Se reevalúa si el SLA objetivo sube por encima de 99.5 %.
