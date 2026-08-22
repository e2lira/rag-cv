# ADR-0001 — AWS App Runner como cómputo de producción

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aceptada |
| **Fecha** | 2026-08-22 |
| **RFCs afectados** | RFC-0007, RFC-0008 |

## Contexto

La aplicación es un servicio HTTP con estado en base de datos, tráfico bajo y variable
(evaluadores consultando de forma esporádica), con streaming SSE de respuestas largas y con
necesidad de acceso privado a una base de datos en VPC. El presupuesto objetivo es ≤ USD 60
mensuales (RNF-6) y la disponibilidad objetivo 99.5 % (RNF-4). El equipo es de una persona.

## Decisión

Se despliega en **AWS App Runner**, con imagen desde ECR, VPC Connector hacia subredes privadas
para alcanzar RDS, y salida directa a Bedrock por la ruta gestionada del servicio.

## Alternativas consideradas

| Alternativa | A favor | En contra | Por qué se descarta |
| :--- | :--- | :--- | :--- |
| **App Runner** | Sin balanceador ni NAT que operar; TLS y dominio incluidos; despliegue progresivo con health check; autoescalado; soporta SSE | Menos control de red; costo mínimo mensual no nulo; regiones limitadas | **Elegida** |
| **ECS Fargate + ALB** | Control total, blue/green nativo, mismas primitivas que el resto de la organización | ALB (~USD 18/mes) + NAT (~USD 32/mes) + más IaC y más piezas que operar para una persona | El coste fijo casi duplica el presupuesto sin aportar nada que el reto necesite |
| **Lambda + API Gateway** | Coste casi cero en reposo; escala a cero | Arranque en frío incompatible con RNF-1; SSE requiere Function URLs con *response streaming* y complica el agente; conexiones a RDS necesitan RDS Proxy (coste y pieza extra); límite de 15 min irrelevante pero el modelo de concurrencia complica el pool | El streaming y las conexiones persistentes a Postgres lo convierten en la opción con más fricción |
| **EC2 + Docker Compose** | Máximo control, coste bajo | Hay que parchear, monitorizar y operar el host; sin autoescalado ni despliegue progresivo | Es lo que ya hace QA; repetirlo en PROD no demuestra criterio de operación en AWS |
| **Bedrock AgentCore Runtime** | Gestionado para agentes, sesiones e identidad integradas | Acopla el diseño a un runtime concreto y reduce lo que se puede demostrar sobre despliegue y operación propios; menos control del contrato HTTP | El reto evalúa cómo se despliega y opera; delegarlo entero resta señal |

## Consecuencias

**Positivas**

- Coste de PROD dentro del presupuesto (≈ USD 46–68/mes estimados, RFC-0007 §10).
- Despliegue progresivo con verificación de `/readyz` y reversión automática si la revisión
  nueva no arranca.
- Sin NAT Gateway: el ahorro más grande de la arquitectura.
- Una sola pieza de cómputo que operar, coherente con un equipo de una persona.

**Negativas / deuda aceptada**

- Sin control fino de red para el tráfico saliente hacia Bedrock (sale por la ruta gestionada,
  no por la VPC).
- Menos opciones de despliegue avanzado (canary por porcentaje, por ejemplo).
- Instancia mínima siempre encendida: no se escala a cero, porque el arranque en frío rompería
  RNF-1.
- Dependencia de la disponibilidad regional del servicio.

**Condición de revisión**

Se reabre si ocurre cualquiera de estas: (a) se exige que el tráfico a Bedrock no salga a
internet, lo que obliga a VPC endpoints y hace más natural Fargate; (b) el tráfico sostenido
supera ~50 req/min, donde el coste por instancia de App Runner deja de ser competitivo;
(c) se necesita despliegue canary por porcentaje de tráfico.
