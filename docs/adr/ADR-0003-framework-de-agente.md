# ADR-0003 — Strands Agents como capa de agente, sobre boto3

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aceptada |
| **Fecha** | 2026-08-22 |
| **RFCs afectados** | RFC-0004 |

## Contexto

El agente necesita: decidir cuándo buscar (no siempre hace falta), invocar herramientas
tipadas, transmitir la respuesta token a token, heredar credenciales del rol de la instancia en
AWS y emitir telemetría. El equipo es de una persona y el proyecto debe ser auditable por otro
modelo, lo que penaliza cualquier framework con mucha indirección.

## Decisión

Se usa **Strands Agents SDK** con el proveedor `BedrockModel`, exponiendo dos herramientas
propias mediante el decorador `@tool`. Todo el uso de Strands queda confinado a `app/agent/`.

## Alternativas consideradas

| Alternativa | A favor | En contra | Por qué se descarta |
| :--- | :--- | :--- | :--- |
| **Strands Agents** | Herramientas por decorador con esquema derivado de la firma y el docstring; bucle de razonamiento resuelto; streaming; telemetría OTEL; credenciales por cadena por defecto; mantenido por AWS y alineado con Bedrock | Dependencia joven, API en evolución; abstrae el bucle, que hay que acotar explícitamente | **Elegida** |
| **boto3 `converse` / `converse_stream` a pelo** | Cero dependencias, control absoluto del bucle | Hay que implementar el bucle de herramientas, el esquema JSON de cada una, el manejo de `toolUse`/`toolResult` y el streaming. Son ~300 líneas de código propio, propenso a errores y sin valor diferencial | El código que se ahorra no es donde está el criterio a demostrar |
| **LangChain / LangGraph** | Ecosistema enorme, muchos integradores | Más abstracción y más dependencias transitivas de las que este caso necesita; el grafo aporta poco con dos herramientas; superficie mayor para auditar | Sobredimensionado para el alcance |
| **Bedrock Agents (gestionado)** | Sin código de orquestación; herramientas como Lambdas | El prompt y la política de razonamiento quedan parcialmente fuera del repositorio, lo que dificulta versionarlos y evaluarlos; cada herramienta pasa a ser una Lambda con su propio despliegue | Rompe el versionado del prompt y el gate de evaluación de RFC-0009 |

## Consecuencias

**Positivas**

- El código del agente cabe en un archivo legible; el Auditor puede verificarlo.
- Autenticación por rol IAM sin manejar credenciales (RFC-0007 §7).
- Streaming y telemetría sin trabajo adicional.
- Las herramientas son funciones Python normales: se prueban sin levantar el agente.

**Negativas / deuda aceptada**

- Riesgo de cambios incompatibles en una API joven. Se mitiga fijando la versión con lock y
  confinando el uso a `app/agent/`, de modo que un cambio de framework toque un solo paquete.
- El bucle interno no es totalmente visible: por eso RFC-0004 §8 impone topes propios de
  iteraciones y llamadas a herramientas en lugar de confiar en los del framework.

**Condición de revisión**

Se reabre si un cambio incompatible del SDK cuesta más de dos días de adaptación, si se
necesita un control del bucle que el framework no permita, o si el sistema pasa a requerir
orquestación multiagente con estado, donde un grafo explícito compensa su coste.
