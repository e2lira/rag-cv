# Hoja de ruta: Fases 1–4 e implementación en AWS

Una sola vista que recorre la entrega del proyecto: la hoja de ruta en cuatro fases, qué
produce cada fase y el destino final, la implementación de producción en AWS.

```mermaid
flowchart TB
    subgraph RUTA["HOJA DE RUTA · rag-cv"]
        direction TB
        subgraph F1["FASE 1 · Fundaciones"]
            direction TB
            F1a["Estructura Python por capas<br/>Domain / Application / Adapters"]
            F1b["Esquema PostgreSQL + pgvector<br/>source ledger · migraciones"]
            F1c["Pruebas unitarias y<br/>evaluación base de recuperación"]
        end
        subgraph F2["FASE 2 · Ingestión RAG"]
            direction TB
            F2a["Lector de CV + chunking<br/>por secciones"]
            F2b["Embeddings Bedrock (Titan V2)<br/>HNSW + RRF"]
            F2c["Ingestión idempotente +<br/>API FastAPI + pruebas"]
        end
        subgraph F3["FASE 3 · Entornos y AWS"]
            direction TB
            F3a["DEV (Windows) · QA (Ubuntu)<br/>PROD (AWS) automatizados"]
            F3b["S3 versionado + SSE-KMS<br/>IAM · EventBridge · scheduler"]
            F3c["Secrets Manager ·<br/>observabilidad CloudWatch"]
        end
        subgraph F4["FASE 4 · Confiabilidad operativa"]
            direction TB
            F4a["Mantenimiento HNSW<br/>por umbral y ventana"]
            F4b["Evaluación RAG +<br/>pruebas de carga"]
            F4c["Recuperación retry/DLQ<br/>y revisión de seguridad"]
        end
        F1 --> F2 --> F3 --> F4
    end

    subgraph AWS["IMPLEMENTACIÓN AWS · PROD (us-east-2)"]
        direction TB
        A1["AWS App Runner<br/>+ Amazon ECR"]
        A2["Amazon RDS<br/>PostgreSQL 16 + pgvector"]
        A3["Amazon S3 + Amazon Bedrock<br/>cv.md · generación + embeddings"]
        A4["Secrets Manager · CloudWatch<br/>EventBridge · IAM · Budgets"]
    end

    F4 ==>|"despliegue por digest"| AWS
```

## Lectura de la imagen

- **Fases 1 y 2** construyen el núcleo (capas, base de datos, ingesta RAG) sin depender de
  infraestructura específica de AWS: el código habla con puertos, no con servicios.
- **Fase 3** introduce los tres entornos y la infraestructura AWS (S3, IAM, EventBridge,
  secretos, observabilidad).
- **Fase 4** endurece la operación: mantenimiento de índices por umbral, evaluación de
  calidad y recuperación ante fallos.
- **AWS (PROD)** es el estado final: cómputo en App Runner desde ECR, datos en RDS privado,
  fuente del CV en S3 y modelos en Bedrock, todo con IAM de mínimo privilegio.

El detalle de cada fase está en [`README.md`](../../README.md#hoja-de-ruta) y la topología
completa de producción en [`arquitectura-aws.md`](arquitectura-aws.md).
