# Arquitectura C4 de `rag-cv`

Modelo C4 en tres niveles: **Contexto** (L1), **Contenedor** (L2) y **Componente** (L3).
El nivel de código (L4) se omite: el repositorio aún está en fase de planificación y no
existe la implementación Python. La estructura de paquetes de referencia está en
RFC-0001 §5.

## Nivel 1 — Contexto del sistema

```mermaid
flowchart LR
    R["Reclutador técnico<br/>[Persona]"]
    HM["Hiring manager<br/>[Persona]"]
    EV["Evaluador del reto<br/>[Persona]"]
    INT["Integrador externo<br/>[Sistema]"]
    DEV["Desarrollador<br/>[Persona]"]

    RCV["rag-cv<br/>[Sistema de software]<br/>Agente conversacional sobre CV"]

    R -->|"pregunta"| RCV
    HM -->|"pregunta"| RCV
    EV -->|"evalúa criterio"| RCV
    INT -->|"API · X-API-Key"| RCV
    DEV -->|"edita corpus/cv.md"| RCV

    RCV -->|"generación + embeddings"| BR["Amazon Bedrock<br/>[Sistema externo]"]
    RCV -->|"recuperación híbrida"| PG["PostgreSQL + pgvector<br/>[Sistema externo]"]
    RCV -->|"lee cv.md (versiones)"| S3["Amazon S3<br/>[Sistema externo]"]
    RCV -->|"secretos"| SM["AWS Secrets Manager<br/>[Sistema externo]"]
    RCV -->|"logs · métricas · alarmas"| CW["Amazon CloudWatch<br/>[Sistema externo]"]
```

## Nivel 2 — Contenedores

```mermaid
flowchart TB
    U["Evaluador / Integrador<br/>[Cliente]"]
    CI["CI/CD<br/>[GitHub Actions]"]

    subgraph AR["AWS App Runner · contenedor rag-cv (1 vCPU / 2 GB)"]
        API["API FastAPI + Uvicorn<br/>:8080"]
        AGENT["Agente Strands<br/>prompt + herramientas"]
        RET["Retriever híbrido<br/>HNSW + BM25 + RRF"]
        WORKER["Worker de ingesta<br/>idempotente"]
    end

    U -->|"HTTPS / SSE · X-API-Key"| API
    API --> AGENT --> RET

    RET -->|"consulta vectorial + léxica"| RDS[("Amazon RDS<br/>PostgreSQL 16 + pgvector")]
    AGENT -->|"InvokeModel"| BR["Amazon Bedrock<br/>Haiku 4.5 + Titan V2"]
    RET -->|"embed query"| BR
    WORKER -->|"lee cv.md"| S3["Amazon S3<br/>versionado · SSE-KMS"]
    WORKER -->|"indexa chunks"| RDS
    API -->|"lee secretos"| SM["AWS Secrets Manager"]
    AR -.->|"logs · métricas"| CW["Amazon CloudWatch"]

    S3 -->|"evento Object Created"| EB["Amazon EventBridge"] -->|"invoca"| WORKER
    CI -->|"push imagen por digest"| ECR["Amazon ECR"] -->|"despliega"| AR
```

## Nivel 3 — Componentes (capas del contenedor)

```mermaid
flowchart TB
    C["Cliente HTTP<br/>(reclutador, integrador)"]

    subgraph APP["Contenedor rag-cv (FastAPI + Uvicorn, :8080)"]
        MW["Middleware<br/>API Key · rate limit · request-id"]
        API["Capa API<br/>/v1/chat · /v1/chat/stream · /healthz"]
        SVC["Capa de servicio<br/>orquestación de conversación"]
        AG["Capa de agente<br/>Strands Agent + tools"]
        RET["Retriever híbrido<br/>HNSW + BM25 + RRF"]
        ING["Ingestión<br/>loader · chunker · indexer"]
        REPO["Repositorios<br/>psycopg / SQLAlchemy Core"]
        PRV["Proveedores<br/>boto3 · Bedrock · LLM"]
    end

    subgraph AWS["Amazon Bedrock"]
        LLM["Claude Haiku 4.5<br/>(generación)"]
        EMB["Titan Text Embeddings V2<br/>(1024 dim)"]
    end

    DB[("PostgreSQL 16 + pgvector<br/>chunks · conversaciones")]
    OBS["Logs JSON · OTEL · métricas"]

    C -->|"X-API-Key"| MW --> API --> SVC --> AG
    AG -->|"tool call"| RET --> REPO --> DB
    AG -->|"InvokeModel"| PRV --> LLM
    RET -->|"embed query"| PRV --> EMB
    ING --> REPO
    SVC --> REPO
    APP -.-> OBS
```

## Reglas que los diagramas deben respetar

- Las dependencias apuntan hacia el centro: `api → services → agent → retrieval → db`.
  Ningún módulo interior importa uno exterior (RFC-0001 §4).
- El contenedor de App Runner **no** accede a RDS por internet: lo hace por el VPC Connector
  a subredes privadas (RFC-0007 §6).
- Bedrock es un sistema externo; el acceso se resuelve por rol IAM de instancia, sin claves
  de proveedor en producción (RFC-0007 §7.1).
