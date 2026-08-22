# ADR-0006 — El entorno de entrega de la PoC es QA (VPS Ubuntu); AWS queda diferido

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aceptada |
| **Fecha** | 2026-08-22 |
| **Modifica a** | ADR-0001 (App Runner sigue siendo la decisión de PROD, pero PROD sale del alcance de la PoC) |
| **RFCs afectados** | RFC-0016, RFC-0007, RFC-0015, RFC-0008, RFC-0010, RFC-0001 |

## Contexto

El diseño vigente contempla tres entornos: DEV (Windows nativo), QA (VPS Ubuntu de Hostinger) y
PROD (AWS App Runner + RDS). PROD es donde viven las decisiones más caras del proyecto:
Terraform con cinco módulos, VPC Connector, NAT o PrivateLink, Secrets Manager, CloudWatch con
diez alarmas y sus pruebas de recuperación (RFC-0007 §6, §9; RFC-0010 §6).

Lo que cambió es el objetivo. Esto es una **prueba de concepto evaluada por criterio técnico**,
y el propio análisis de costos ya lo había anticipado:

> Una PoC puede demostrar el producto y la conversación, pero **no** valida RNF-4 (99.5 %),
> RNF-1 (latencia) ni la operación real; esos criterios exigen la arquitectura PROD.
> — `docs/diagramas/costos-aws.md`

Es decir: la infraestructura de PROD cuesta entre USD 46 y 60 al mes y **no aporta ninguna
evidencia adicional sobre lo que la PoC tiene que demostrar** — que el agente recupera bien,
responde fundamentado y se abstiene cuando no sabe. Ese juicio se emite sobre QA con corpus real
exactamente igual que sobre PROD.

Mantener PROD dentro del alcance tiene además un coste que no es económico: obliga a construir,
auditar y operar Terraform, IAM, red privada y observabilidad de AWS **antes** de tener el
producto validado. Es la clase de inversión que se hace cuando ya sabés que el producto funciona,
no para averiguarlo.

## Decisión

**El entorno de entrega de la PoC es QA: un único VPS Ubuntu Server 24.04.** La PoC se demuestra,
se evalúa y se audita ahí. Cómo corren los procesos en ese host lo decide ADR-0010; este ADR fija
el *dónde*, no el *cómo*.

**PROD sobre AWS queda diferido, no cancelado.** ADR-0001 (App Runner), ADR-0002 (pgvector
propio) y los RFCs de infraestructura AWS **siguen siendo `Aprobado` y no se editan**: son el
camino de promoción cuando la PoC pase el juicio técnico. Se leen junto a RFC-0016, que declara
qué queda dentro y qué queda fuera del alcance vigente.

La consecuencia directa: **la aplicación deja de depender de AWS en tiempo de ejecución.** Eso
obliga a resolver las dos dependencias que quedaban —embeddings y generación—, que se deciden en
ADR-0007 y ADR-0008.

## Alternativas consideradas

| Alternativa | A favor | En contra | Por qué se descarta |
| :--- | :--- | :--- | :--- |
| **QA (VPS) como entorno de entrega, AWS diferido** | Coste fijo bajo y conocido. Cero infraestructura que construir antes de validar el producto. Fuerza a que la app no dependa de nada específico de AWS — que es justo lo que RFC-0007 §5.3 ya declaraba como beneficio buscado | No valida RNF-4 (99.5 %) ni la operación real de PROD. Un solo host: sin alta disponibilidad, sin autoescalado. El VPS pasa a ser una dependencia de arquitectura con requisitos de memoria propios | **Elegida** |
| Desplegar PROD en AWS con Free Tier / créditos | Demuestra la arquitectura final; los créditos cubren el período de demostración | Bedrock es pago por token sin free tier garantizado. Free Tier y créditos aplican solo a cuentas nuevas. Exige Terraform, IAM, red privada y alarmas **antes** de validar el producto, y `terraform destroy` al terminar | Paga la complejidad de PROD para obtener la misma evidencia que da QA. Y deja la demo con fecha de caducidad atada a una cuenta |
| Mantener los tres entornos con PROD activo | Ningún documento cambia | USD 46–60/mes indefinidos y una superficie de operación que nadie va a operar durante la PoC | Sostiene un entorno que no produce evidencia, y su coste real es el tiempo de construirlo y auditarlo |
| Lambda + Function URL | *Always free*, el costo mínimo absoluto | Arranque en frío y streaming SSE complicado — los motivos por los que ADR-0001 ya lo descartó | No demuestra el diseño de despliegue, y reintroduce un problema ya resuelto |
| Marcar los RFCs de AWS como `Obsoleto` | Índice más limpio | Destruye trabajo de diseño válido y convierte un aplazamiento en una cancelación. Cuando la PoC pase, habría que reescribirlos | Confunde "fuera de alcance hoy" con "decisión revertida". Son cosas distintas y el índice debe distinguirlas |

## Consecuencias

**Positivas**

- **Coste de infraestructura conocido y fijo**: un VPS. Desaparecen App Runner, RDS, ECR, NAT y
  CloudWatch de la factura y de la superficie de operación.
- **El diseño de PROD no se quema.** RFC-0007 §6 sigue intacto y disponible para el día que
  corresponda. Lo que sí cambia es el artefacto: ADR-0010 lo convierte en un commit en vez de una
  imagen, y declara como deuda que la imagen de RFC-0015 nunca se habrá ejercitado en QA.
- **La portabilidad deja de ser una promesa.** RFC-0007 §5.3 decía que un VPS "fuerza a que la
  aplicación no dependa de nada específico de AWS más allá de Bedrock". Al quitar también
  Bedrock, esa frase pasa a ser literal y verificable.
- **Menos secretos de larga vida.** Se retiran las claves del usuario IAM `rag-cv-qa-invoker`
  del `.env` del VPS y su rotación cada 90 días (RFC-0007 §5.2).

**Negativas / deuda aceptada**

- **RNF-4 (99.5 % de disponibilidad) no se valida.** Un host único no tiene alta disponibilidad.
  Se acepta explícitamente: el umbral se declara **no verificado** en la PoC, no se declara
  cumplido. Fingir lo contrario sería el peor resultado posible de este documento.
- **RNF-6 (costo de PROD ≤ USD 60/mes) queda sin medir**, porque no hay PROD.
- **El VPS pasa a ser una dependencia de arquitectura.** Su memoria condiciona qué modelos se
  pueden autoalojar (ADR-0007). Antes era un detalle de compra; ahora es un requisito con número
  y hay que declararlo (RFC-0016 §5).
- **Un solo host es un punto único de fallo** para la demo: si el VPS cae, no hay servicio.
  Aceptable para una PoC evaluada en una ventana acotada; inaceptable para producción.
- La documentación pasa a leerse en dos capas: los RFCs de AWS más el RFC de alcance que declara
  qué está diferido. Es una lectura más, y es el precio de no editar documentos aprobados.

## Condición de revisión

Se reabre cuando: (a) la PoC pase el juicio técnico y el proyecto necesite operación real con
compromiso de disponibilidad; (b) aparezca un requisito de residencia de datos, cumplimiento o
integración que solo AWS satisfaga; o (c) la carga supere lo que un host único sostiene con la
latencia de RNF-1.

Cuando eso ocurra, este ADR no se revierte: se cierra declarando cumplida la condición, y
RFC-0007 §6 vuelve a ser el documento normativo de PROD sin haber sido tocado.
