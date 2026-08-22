# Documentación — Agente de CV (rag-cv)

Documentación viva del reto **Full Stack AI — Subdirección (Banorte)**: diseñar, construir,
desplegar y operar un agente conversacional que representa una trayectoria profesional y
responde preguntas sobre perfil, experiencia, habilidades y proyectos.

La documentación se produce y se consume bajo la metodología multiagente **ADU**
(Arquitecto · Desarrollador · Auditor). Ningún documento es decorativo: cada RFC es el
**contrato** que el Desarrollador implementa y que el Auditor verifica.

---

## 1. Mapa de documentos

| Documento | Qué responde | Dueño (rol ADU) |
| :--- | :--- | :--- |
| [PRD.md](./PRD.md) | Qué construimos y por qué; alcance, usuarios, métricas de éxito | Arquitecto |
| [adu/ADU-PROCESO.md](./adu/ADU-PROCESO.md) | Cómo trabajamos: roles, handoffs, gates, DoR/DoD | Arquitecto |
| [adu/PLANTILLA-RFC.md](./adu/PLANTILLA-RFC.md) | Estructura obligatoria de todo RFC | Arquitecto |
| [adu/PLANTILLA-ADR.md](./adu/PLANTILLA-ADR.md) | Estructura de una decisión arquitectónica | Arquitecto |
| [adu/prompts/](./adu/prompts/README.md) | Prompts de ejecución de los tres roles, listos para pegar | Arquitecto |
| `adr/` | Decisiones tomadas y sus alternativas descartadas | Arquitecto |
| `rfc/` | Diseño ejecutable por componente | Arquitecto → Desarrollador |
| `auditorias/` | Informes de auditoría archivados de los PR con veredicto `FAIL` | Auditor |

## 2. Índice de RFCs

| RFC | Título | Estado | Depende de |
| :--- | :--- | :--- | :--- |
| [RFC-0001](./rfc/RFC-0001-arquitectura-general.md) | Arquitectura general y límites del sistema | Aprobado | — |
| [RFC-0002](./rfc/RFC-0002-ingesta-y-chunking.md) | Ingesta del CV, normalización y chunking | Aprobado | 0001, 0006 |
| [RFC-0003](./rfc/RFC-0003-retrieval-hibrido-rrf.md) | Recuperación híbrida (HNSW + BM25 + RRF) | Aprobado | 0002, 0006 |
| [RFC-0004](./rfc/RFC-0004-capa-agente-strands.md) | Capa de agente con Strands Agents | Aprobado | 0003 |
| [RFC-0005](./rfc/RFC-0005-api-rest-y-autenticacion.md) | API REST, contrato y autenticación por API Key | Aprobado | 0004 |
| [RFC-0006](./rfc/RFC-0006-modelo-de-datos-y-migraciones.md) | Modelo de datos PostgreSQL/pgvector y migraciones | Aprobado | 0001 |
| [RFC-0007](./rfc/RFC-0007-entornos-e-infraestructura.md) | Entornos DEV/QA/PROD e infraestructura | Aprobado | 0001 |
| [RFC-0008](./rfc/RFC-0008-cicd-y-release.md) | CI/CD, versionado y estrategia de release | Aprobado | 0007, 0009 |
| [RFC-0009](./rfc/RFC-0009-evaluacion-y-guardrails.md) | Evaluación del agente, guardrails y seguridad de contenido | Aprobado | 0004 |
| [RFC-0010](./rfc/RFC-0010-observabilidad-costos-y-runbook.md) | Observabilidad, costos y operación | Aprobado | 0005, 0007 |
| [RFC-0011](./rfc/RFC-0011-entorno-dev-windows-nativo.md) | Entorno de desarrollo nativo en Windows | Aprobado | 0006, 0007 |
| [RFC-0012](./rfc/RFC-0012-capa-de-embeddings-enchufable.md) | Capa de embeddings enchufable: Titan V2 por defecto | Aprobado | 0002, 0003, 0006 |
| [RFC-0013](./rfc/RFC-0013-capa-de-proveedores-llm.md) | Proveedores de modelo (Model Loop) y parametrización | Aprobado | 0004 |
| [RFC-0014](./rfc/RFC-0014-disciplina-tdd.md) | Disciplina TDD verificable | Aprobado | 0008, 0009 |
| [RFC-0015](./rfc/RFC-0015-empaquetado-docker-y-despliegue.md) | Empaquetado Docker y artefactos de despliegue | Aprobado | 0007, 0008, 0012 |

## 3. Índice de ADRs

| ADR | Decisión | Estado |
| :--- | :--- | :--- |
| [ADR-0001](./adr/ADR-0001-computo-en-produccion.md) | App Runner como cómputo de PROD | Aceptada |
| [ADR-0002](./adr/ADR-0002-motor-de-recuperacion.md) | pgvector propio en vez de Bedrock Knowledge Bases | Aceptada |
| [ADR-0003](./adr/ADR-0003-framework-de-agente.md) | Strands Agents sobre boto3 directo | Aceptada |
| [ADR-0004](./adr/ADR-0004-modelo-de-embeddings.md) | Titan Text Embeddings V2 por defecto, Nomic como contingencia | Aceptada |
| [ADR-0005](./adr/ADR-0005-proveedor-de-generacion.md) | Proveedor de generación por parametrización | Aceptada |

## 4. Cómo leer esto por primera vez

1. `PRD.md` — el problema y el criterio de éxito.
2. `adu/ADU-PROCESO.md` — cómo se produce y se valida cada entregable.
3. `rfc/RFC-0001` — la foto completa del sistema.
4. El resto de RFCs en orden de dependencia.

**Si vas a montar el entorno de desarrollo:** `rfc/RFC-0011` es el documento normativo.
DEV es Windows nativo (Python + PostgreSQL + pgvector, sin Docker), QA es Ubuntu y PROD es AWS.

**Si vas a implementar:** `rfc/RFC-0014` (TDD) y `adu/prompts/PROMPT-DESARROLLADOR-TDD.md`.
La primera entrega de todo RFC es la suite de tests **en rojo**, en su propio commit.

## 5. Convenciones

- **Idioma:** documentación en español; código, identificadores y logs en inglés.
- **Estado de un RFC:** `Borrador` → `En revisión` → `Aprobado` → `Implementado` → `Obsoleto`.
- Un RFC **no se edita** una vez `Implementado`: se supersede con un RFC nuevo que lo referencie.
- Toda decisión con alternativas descartadas se registra como **ADR**, no en el cuerpo del RFC.
- Un RFC que modifica a otro lo declara en su cabecera (`Supersede`), y el modificado no se edita
  en su sitio: se lee siempre junto al que lo modifica.
- Los identificadores (`RFC-000N`) son inmutables y se citan en commits: `feat(rag): ... [RFC-0003]`.
