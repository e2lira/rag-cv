# Costos mínimos de producción en AWS

Investigación del costo de mantener `rag-cv` en producción en AWS (región `us-east-2`),
con el objetivo de cumplir **RNF-6: costo total en reposo ≤ USD 60 / mes**.

> **Fecha de verificación:** 2026-08-22. Los precios marcados como *(verificado)* se leyeron
> de las páginas oficiales de precios de AWS; los *(estimado)* provienen de la tabla de costos
> de RFC-0007 §10 y dependen del modelo y del tráfico.

## Resumen ejecutivo

| Escenario | Costo mensual estimado | Frente a RNF-6 (USD 60) |
| :--- | :--- | :--- |
| **Mínimo (piso teórico, casi sin tráfico)** | ≈ USD 33–38 | 55–63 % del presupuesto |
| **Realista (≈ 1 000 turnos/mes)** | ≈ USD 46–60 | Dentro del presupuesto |
| **Pico (abuso o tráfico alto)** | > USD 60 | Dispara alertas de Budgets |

La conclusión: el diseño **sí cabe** en USD 60/mes con margen para tráfico real de evaluación.
El costo dominante es el cómputo siempre encendido (App Runner + RDS), no la inferencia.

## Desglose por servicio

| Servicio | Configuración | Precio unitario | Costo mensual | Fuente |
| :--- | :--- | :--- | :--- | :--- |
| **AWS App Runner** | 1 vCPU / 2 GB, 1 instancia provisionada 24/7 | $0.007 / GB-h provisionado · $0.064 / vCPU-h activo | ≈ USD 10–13 | *(verificado)* |
| **Amazon RDS** | `db.t4g.micro`, Single-AZ | $0.016 / h + gp3 $0.115 / GB-mes (20 GB) | ≈ USD 14 | *(verificado — precio de instancia estable)* |
| **Amazon Bedrock** | Claude Haiku 4.5 (generación) + Titan V2 (embeddings) | ~$1 / 1M tok in · ~$5 / 1M tok out | ≈ USD 5–15 | *(estimado — depende de turnos)* |
| **Amazon ECR** | < 1 GB de imágenes | $0.10 / GB-mes | < USD 0.10 | *(verificado)* |
| **AWS Secrets Manager** | 2 secretos | $0.40 / secreto-mes | USD 0.80 | *(verificado)* |
| **Amazon CloudWatch** | Logs 30 días + métricas EMF | $0.50 / GB ingesta · $0.03 / GB almacenado | ≈ USD 2–4 | *(verificado — depende de volumen)* |
| **Amazon S3** | cv.md versionado (KB) | $0.023 / GB-mes | < USD 0.10 | *(verificado — despreciable)* |
| **Amazon EventBridge** | 2 reglas, pocos eventos | $1 / 1M eventos | < USD 0.10 | *(verificado — despreciable)* |
| **AWS Budgets** | 1 presupuesto | $0.10 / presupuesto-día > 10k | USD 0 | *(gratis en este volumen)* |

### Cálculo del cómputo (App Runner, verificado)

Con la tarifa publicada para `us-east-2` (US East / Ohio):

- **Instancia provisionada** (caliente, sin tráfico): 2 GB × $0.007 × 24 h × 30 d = **USD 10.08/mes**.
- **Cómputo activo** (al procesar peticiones): 1 vCPU × $0.064 + 2 GB × $0.007, cobrado por
  segundo. Para ~1 000 turnos/mes con respuestas de ~6 s el costo activo es de **unos USD 1–3**.
- AWS publica un ejemplo "API ligera sensible a latencia" (1 instancia 1 vCPU/2 GB) en
  **USD 25.50/mes**; nuestro perfil es más austero porque el tráfico es esporádico.

El autoescalado a **cero** se descarta en la v1: el arranque en frío (~2 s) rompería RNF-1
(latencia de primer token ≤ 2 s), así que se mantiene **mínimo 1 instancia** (ADR-0001).

## Qué NO se paga (ahorros estructurales del diseño)

Estos son los ahorros deliberados que mantienen el costo bajo; vienen de decisiones ya
documentadas y no deben revertirse sin reabrir la ADR correspondiente:

| Ahorro | Decisión | Impacto |
| :--- | :--- | :--- |
| **Sin NAT Gateway** | App Runner sale por su ruta gestionada (ADR-0001) | Ahorra ~USD 32/mes |
| **Sin ALB** | App Runner incluye balanceador y TLS | Ahorra ~USD 18/mes |
| **Sin RDS Proxy** | El pool de `psycopg` basta para 2 workers | Ahorra ~USD 10+ /mes |
| **RDS Single-AZ, `t4g.micro`** | SLA objetivo 99.5 % no exige multi-AZ (PRD §11) | Evita duplicar la base |
| **Embeddings Titan V2, no Nomic API** | Misma credencial y región que la generación | Sin costo extra de embeddings |
| **IAM por ARN de modelo** | `bedrock:InvokeModel` sin `Resource: "*"` (RFC-0007 §7.1) | Evita factura por modelos caros |

## Volatilidad y palancas de control

- **Bedrock es la parte variable.** El costo se acota con: `max_tokens=1024`, máximo 2 llamadas
  a herramientas por turno, límite de 30 req/min por clave y la alarma `CostDaily` > USD 3
  (RFC-0010 §6, §8).
- **Presupuesto con alertas al 50/80/100 %** de USD 60 en AWS Budgets (RFC-0007 §6.2).
- **Palancas si se excede el presupuesto:** bajar `RETRIEVAL_TOP_K`, reducir memoria de
  conversación, o en última instancia reabrir ADR-0001 para evaluar Fargate o escala a cero
  fuera de horario.

## POC sin costo

Para una prueba de concepto se puede operar con costo **cero o casi cero**, aceptando
desviaciones respecto a la arquitectura PROD. Lo único que no se puede eliminar sin cambiar el
cómputo es la instancia siempre encendida de App Runner (~USD 10/mes).

| Opción | Cómputo | Base de datos | Costo real | Fidelidad al diseño |
| :--- | :--- | :--- | :--- | :--- |
| **1. Cuenta nueva + créditos** | App Runner (como PROD) | RDS | USD 0 (cubierto por créditos) | Total |
| **2. EC2 `t2.micro` Free Tier** | Contenedor vía `docker compose` | Postgres+pgvector en el mismo host | USD 0 infra + Bedrock | Alta (patrón QA) |
| **3. Lambda + Function URL** | Serverless | RDS Free Tier | ≈ USD 0 | Baja (arranque en frío, SSE) |

### Opción 1 — Créditos de cuenta nueva (verificado 2026-08-22)

AWS da hasta **USD 200 en créditos** en cuentas nuevas (USD 100 inmediatos + hasta USD 100
más), en un plan *Free* de 6 meses sin cobros sorpresa. Cubre de sobra la arquitectura real
(≈ USD 46–60/mes) durante el período de demostración. Limitación: el plan *Free* restringe a
"servicios selectos", por lo que Bedrock probablemente requiera pasar a plan *Paid* (donde los
créditos también aplican).

### Opción 2 — Free Tier clásico + EC2

El *Free Tier* de 12 meses incluye **750 h/mes de EC2 `t2.micro`** y **750 h/mes de RDS
`db.t4g.micro`**. Correr el mismo contenedor con `docker compose` sobre la instancia EC2
replica el patrón de QA (RFC-0007 §5) a costo de infraestructura USD 0. Bedrock sigue siendo
pay-per-token: para decenas de consultas son centavos.

### Opción 3 — Lambda + Function URL

Lambda es *always free* (1M invocaciones/mes) y se combina con RDS Free Tier. Es la opción de
menor costo, pero reintroduce el arranque en frío y complica el streaming SSE, motivos por los
que ADR-0001 descartó Lambda para PROD. No demuestra el diseño de despliegue final.

### Precauciones comunes a las tres

- **Bedrock no tiene free tier de modelos garantizado**: es pago por token, sin importar el
  resto de la infra.
- El *Free Tier* y los créditos aplican a **cuentas nuevas**; una cuenta existente no los
  recupera.
- Configurar **AWS Budgets con alerta a USD 1** y ejecutar `terraform destroy` al terminar la
  demo para no dejar recursos facturando.

> **Regla:** una POC puede demostrar el producto y la conversación, pero **no** valida RNF-4
> (99.5 %), RNF-1 (latencia) ni la operación real; esos criterios exigen la arquitectura PROD.

## Notas de precisión

- Los precios de Bedrock varían por región y por *service tier* (Standard/Flex/Priority);
  el valor exacto de Haiku 4.5 en `us-east-2` debe confirmarse en la consola de Bedrock antes
  del primer despliegue (auditoría A-13 de RFC-0007).
- RDS tiene *Free Tier* de 750 h/mes de `db.t4g.micro` en cuentas nuevas: durante el primer
  mes el costo de base puede ser USD 0, pero **no** se asume en el presupuesto operativo.
