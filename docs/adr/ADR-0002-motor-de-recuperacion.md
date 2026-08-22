# ADR-0002 — pgvector propio en lugar de Bedrock Knowledge Bases

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aceptada |
| **Fecha** | 2026-08-22 |
| **RFCs afectados** | RFC-0002, RFC-0003, RFC-0006 |

## Contexto

El corpus es pequeño y muy estructurado (un CV extendido: decenas a un par de centenares de
fragmentos), pero la exigencia de fidelidad es alta: no se tolera una afirmación inventada. El
reto evalúa explícitamente el **criterio** con que se integran contexto y fuentes de
información. Además ya existe una necesidad de base de datos relacional para conversaciones y
cuotas.

## Decisión

Se implementa la recuperación con **PostgreSQL + pgvector**, con búsqueda híbrida (HNSW coseno
+ full-text en español) fusionada por RRF, y chunking propio guiado por la estructura del
documento.

## Alternativas consideradas

| Alternativa | A favor | En contra | Por qué se descarta |
| :--- | :--- | :--- | :--- |
| **PostgreSQL + pgvector** | Vector, léxico y relacional en un motor; control total de chunking, pesos y fusión; sin coste adicional (la BD ya hace falta); portable a QA en contenedor | Hay que construir e instrumentar la recuperación | **Elegida** |
| **Bedrock Knowledge Bases + OpenSearch Serverless** | Gestionado, ingesta y sincronización automáticas, híbrido incluido | OpenSearch Serverless tiene un mínimo de ~USD 100+/mes que dobla el presupuesto; el chunking y el ranking quedan como caja negra; cuesta más portar QA fuera de AWS | Coste incompatible con RNF-6 y, sobre todo, elimina justo la parte que el reto quiere ver |
| **Bedrock Knowledge Bases + Aurora Serverless pgvector** | Gestionado con pgvector debajo | Aurora Serverless v2 tiene un mínimo de capacidad con coste sensiblemente mayor a `db.t4g.micro`; sigue ocultando el chunking | Coste y opacidad |
| **Índice en memoria (FAISS / numpy)** | Cero infraestructura, latencia mínima con este tamaño de corpus | Se pierde la búsqueda léxica sin añadir otra pieza; el índice se reconstruye en cada arranque y por instancia; no hay trazabilidad ni consulta ad hoc | Simplifica de más y no demuestra el criterio de operación de datos |
| **Solo búsqueda léxica con PostgreSQL FTS** | Muy simple y barata | Falla en preguntas parafraseadas, que son la mitad de las que recibe un CV | Insuficiente para RF-2 |

## Consecuencias

**Positivas**

- El chunking, los pesos léxicos, `top_k`, la fusión y el umbral son parámetros explícitos y
  medibles, lo que hace posible la evaluación de RFC-0009.
- Una sola base de datos para todo: menos piezas, transacciones entre corpus y conversaciones.
- QA en un VPS es viable con la misma imagen de Postgres.
- Coste marginal cero respecto a la base de datos que ya se necesitaba.

**Negativas / deuda aceptada**

- Hay que mantener la lógica de recuperación y sus pruebas (≈ el 20 % del código del proyecto).
- La reindexación es responsabilidad propia, incluida su idempotencia.
- Sin reranking gestionado: se asume RRF como fusión y se declara la deuda en RFC-0003 §9.

**Condición de revisión**

Se reabre si el corpus supera ~5 000 fragmentos (donde el ajuste de HNSW empieza a exigir
trabajo real), si se añaden múltiples corpus con permisos distintos, o si el presupuesto crece
lo suficiente para que un servicio gestionado no comprometa RNF-6.
