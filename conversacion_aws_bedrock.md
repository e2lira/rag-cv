# Guía Completa: Publicación de Aplicación Python con AWS Bedrock, Strands y PostgreSQL (pgvector) en AWS App Runner

Este documento recopila toda la arquitectura, configuración de infraestructura de red (VPC), bases de datos vectoriales e implementación de código con el framework Strands para desplegar un Asistente Virtual RAG Híbrido mediante contenedores Docker.

---

## 1. Opciones de Despliegue de la Aplicación Python

Para publicar una aplicación en Python que consuma AWS Bedrock, existen distintas alternativas dependiendo del nivel de abstracción requerido:

| Opción de AWS | Ideal para... | Ventajas |
| :--- | :--- | :--- |
| **AWS App Runner** | Aplicaciones web completas (FastAPI, Flask) | Despliegue directo desde GitHub o Docker, escalado automático, sin gestionar servidores. **(Opción seleccionada)** |
| **AWS Lambda** | APIs de pago por uso o microservicios | Costo casi cero si el tráfico es bajo, requiere empaquetar dependencias o usar contenedores si excede el tamaño. |
| **AWS ECS (Fargate)** | Arquitecturas complejas o contenedores | Control total de la red y contenedores sin administrar instancias EC2. |

---

## 2. Framework de IA: ¿Por qué utilizar Strands Agents?

Para construir un **Asistente Virtual basado en RAG (Retrieval-Augmented Generation)**, la utilización del SDK de **Strands Agents** (un framework open-source de AWS) ofrece una abstracción transparente en comparación con el uso nativo de `boto3`.

### Ventajas de Strands:
* **Mapeo Automático de Herramientas:** Permite transformar cualquier función nativa de Python en una "Tool" ejecutable por el modelo usando decoradores (`@custom_tool`).
* **Autenticación Transparente:** Al desplegarse en AWS App Runner, Strands hereda automáticamente el rol de la instancia de AWS sin necesidad de configurar llaves de API manualmente.
* **Ciclo de Razonamiento:** Maneja de forma interna el ciclo *Chain-of-Thought* para decidir cuándo es necesario consultar la base de conocimientos antes de responder al usuario.

---

## 3. Configuración de la Base de Datos (PostgreSQL + pgvector)

Para el almacenamiento y la recuperación de información desde un archivo `markdown.md`, se utiliza una base de datos **Amazon RDS PostgreSQL** configurada para realizar **búsquedas híbridas** combinando embeddings vectoriales con índices **HNSW** y búsquedas léxicas mediante la fórmula **RRF (Reciprocal Rank Fusion)**.

### Script de Inicialización de la Base de Datos (SQL)

```sql
-- 1. Habilitar la extensión de vectores
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Crear la tabla de documentos
CREATE TABLE documentos_rag (
    id SERIAL PRIMARY KEY,
    contenido TEXT NOT NULL,
    embedding VECTOR(1536), -- 1536 dimensiones para Amazon Titan Text Embedding v2
    tsv_contenido tsvector  -- Para la búsqueda léxica con PostgreSQL Full Text Search
);

-- 3. Crear índice GIN para la búsqueda léxica
CREATE INDEX idx_documentos_tsv ON documentos_rag USING gin(tsv_contenido);

-- 4. Crear índice HNSW para la búsqueda vectorial
CREATE INDEX idx_documentos_hnsw ON documentos_rag USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- 5. Trigger para actualizar automáticamente el índice léxico al insertar texto
CREATE OR REPLACE FUNCTION actualizar_tsv() RETURNS trigger AS $$
begin
  new.tsv_contenido := to_tsvector('spanish', new.contenido);
  return new;
end
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_actualizar_tsv BEFORE INSERT OR UPDATE
ON documentos_rag FOR EACH ROW EXECUTE FUNCTION actualizar_tsv();
```

---

## 4. Estructura y Código del Proyecto

### Archivo: `requirements.txt`
```text
strands-agents>=0.8.0
fastapi
uvicorn
psycopg2-binary>=2.9.0
boto3>=1.34.0
```

### Archivo: `Dockerfile`
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el backend de tu asistente
COPY . .

# Exponer el puerto de producción estándar
EXPOSE 8080

# Iniciar la API con Uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
```

### Archivo: `app.py` (FastAPI + Strands + RRF)
```python
import os
import json
import boto3
import psycopg2
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from strands import Agent
from strands.tools import custom_tool

app = FastAPI()

# Inicializar clientes de AWS
bedrock_runtime = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"))

# Configuración de Conexión a la Base de Datos (Inyectado por App Runner)
DB_CONN_STRING = os.getenv(
    "DATABASE_URL", 
    "postgresql://usuario:password@rds-endpoint.amazonaws.com:5432/mibasedatos"
)

def obtener_embedding(texto: str) -> list:
    """Genera el embedding usando Amazon Titan Embedding V2 (1536 dim)."""
    body = json.dumps({"inputText": texto})
    response = bedrock_runtime.invoke_model(
        modelId="amazon.titan-embed-text-v2:0",
        contentType="application/json",
        accept="application/json",
        body=body
    )
    response_body = json.loads(response.get("body").read())
    return response_body["embedding"]

# --- HERRAMIENTA PERSONALIZADA DE STRANDS PARA BÚSQUEDA HÍBRIDA (RRF) ---
@custom_tool
def buscar_base_conocimiento_hibrida(query: str) -> str:
    """
    Busca información relevante en la base de datos utilizando búsqueda híbrida 
    (Vectores HNSW + Texto plano) combinada mediante Reciprocal Rank Fusion (RRF).
    """
    query_embedding = obtener_embedding(query)
    
    # Consulta SQL con RRF (K=60 constante estándar)
    sql_query = """
    WITH semantic_search AS (
        SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> %s::vector) as rank
        FROM documentos_rag
        ORDER BY embedding <=> %s::vector
        LIMIT 20
    ),
    keyword_search AS (
        SELECT id, ROW_NUMBER() OVER (ORDER BY ts_rank_cd(tsv_contenido, plainto_tsquery('spanish', %s)) DESC) as rank
        FROM documentos_rag
        WHERE tsv_contenido @@ plainto_tsquery('spanish', %s)
        ORDER BY ts_rank_cd(tsv_contenido, plainto_tsquery('spanish', %s)) DESC
        LIMIT 20
    )
    SELECT d.contenido
    FROM documentos_rag d
    JOIN (
        SELECT COALESCE(s.id, k.id) as id,
               COALESCE(1.0 / (60 + s.rank), 0.0) + COALESCE(1.0 / (60 + k.rank), 0.0) as rrf_score
        FROM semantic_search s
        FULL OUTER JOIN keyword_search k ON s.id = k.id
    ) rff ON d.id = rff.id
    ORDER BY rff.rrf_score DESC
    LIMIT 4;
    """
    
    try:
        conn = psycopg2.connect(DB_CONN_STRING)
        cur = conn.cursor()
        cur.execute(sql_query, (query_embedding, query_embedding, query, query, query))
        resultados = cur.fetchall()
        cur.close()
        conn.close()
        
        if not resultados:
            return "No se encontró información relevante en los manuales internos."
            
        contexto = "\n---\n".join([r[0] for r in resultados])
        return f"Información relevante encontrada en la base de conocimientos:\n{contexto}"
        
    except Exception as e:
        return f"Error consultando la base de conocimientos: {str(e)}"

# --- INICIALIZACIÓN DEL AGENTE DE STRANDS ---
agent = Agent(
    model="anthropic.claude-3-5-sonnet",
    tools=[buscar_base_conocimiento_hibrida],
    system_prompt=(
        "Eres un Asistente Virtual experto. Cuando te hagan preguntas sobre la empresa, "
        "procesos o documentación, utiliza SIEMPRE la herramienta 'buscar_base_conocimiento_hibrida' "
        "para fundamentar tus respuestas en base a los documentos internos extraídos de Markdown."
    )
)

class ChatRequest(BaseModel):
    message: str

@app.post("/chat")
def chat(request: ChatRequest):
    try:
        response = agent.run(request.message)
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### Script de Poblamiento Inicial (`script_indexar.py`)
```python
import re
import psycopg2
import boto3
import json

DB_CONN_STRING = "postgresql://usuario:password@rds-endpoint.amazonaws.com:5432/mibasedatos"
bedrock_runtime = boto3.client("bedrock-runtime", region_name="us-east-1")

def cargar_y_partir_markdown(ruta_archivo):
    with open(ruta_archivo, "r", encoding="utf-8") as f:
        texto = f.read()
    chunks = re.split(r'(?=\n## )', texto)
    return [c.strip() for c in chunks if c.strip()]

def obtener_embedding(texto):
    body = json.dumps({"inputText": texto})
    response = bedrock_runtime.invoke_model(
        modelId="amazon.titan-embed-text-v2:0",
        contentType="application/json",
        accept="application/json",
        body=body
    )
    return json.loads(response.get("body").read())["embedding"]

def indexar():
    chunks = cargar_y_partir_markdown("markdown.md")
    conn = psycopg2.connect(DB_CONN_STRING)
    cur = conn.cursor()
    
    print(f"Insertando {len(chunks)} fragmentos en pgvector...")
    for chunk in chunks:
        embedding = obtener_embedding(chunk)
        cur.execute(
            "INSERT INTO documentos_rag (contenido, embedding) VALUES (%s, %s)",
            (chunk, embedding)
        )
    
    conn.commit()
    cur.close()
    conn.close()
    print("¡Indexación híbrida HNSW exitosa!")

if __name__ == "__main__":
    indexar()
```

---

## 5. Seguridad e Infraestructura de Red (VPC)

Para garantizar la máxima seguridad en producción, la comunicación entre **AWS App Runner** y **Amazon RDS PostgreSQL** se realiza exclusivamente de manera interna a través de una VPC privada, evitando la exposición de la base de datos al internet público.

### Configuración de Cortafuegos (Security Groups)

1. **Security Group A: Conector de App Runner (`sg-apprunner-connector`)**
   * **Inbound (Entrada):** Ninguna regla (el tráfico no se origina desde la VPC hacia el contenedor).
   * **Outbound (Salida):** Permitir todo el tráfico (`0.0.0.0/0`) o limitar al puerto `5432` con destino al bloque CIDR de la VPC.

2. **Security Group B: Servidor RDS PostgreSQL (`sg-rds-postgres`)**
   * **Inbound (Entrada):** 
     * **Tipo:** PostgreSQL (TCP)
     * **Puerto:** `5432`
     * **Origen (Source):** Seleccionar el ID del Security Group de origen: **`sg-apprunner-connector`**.

### Interconexión mediante VPC Connector

1. En la consola de **AWS App Runner**, crear un **VPC Connector**.
2. Seleccionar la VPC y las **subredes privadas** (mínimo 2 por alta disponibilidad) donde reside la instancia de RDS.
3. Vincular el Security Group de origen (`sg-apprunner-connector`).
4. En la pestaña de configuración del servicio App Runner (**Networking**), cambiar el tráfico de salida de *Public internet* a *Custom VPC* y asociar el conector creado.

---

## 6. Permisos IAM Requeridos (Instance Role)

El rol de ejecución asignado a AWS App Runner debe contar con la siguiente política adjunta para permitir la invocación de modelos (Generativo y de Embeddings):

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream"
            ],
            "Resource": "*"
        }
    ]
}
```

*Nota: Si se usa AWS Secrets Manager para almacenar las credenciales de la base de datos de manera segura, se debe añadir adicionalmente la acción `secretsmanager:GetSecretValue` apuntando al ARN del secreto correspondiente.*
