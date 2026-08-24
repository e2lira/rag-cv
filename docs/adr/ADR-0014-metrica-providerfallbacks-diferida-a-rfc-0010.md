# ADR-0014 — La métrica `ProviderFallbacks` queda diferida a RFC-0010

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aceptada |
| **Fecha** | 2026-08-24 |
| **Decide** | Arquitecto |
| **RFCs afectados** | RFC-0013, RFC-0010 |

---

## Contexto

RFC-0013 §6.1 y su CA-8 exigen que cada conmutación de proveedor *"emita la métrica
`ProviderFallbacks` y una línea de log de nivel `WARNING`"*. El `WARNING` está implementado
(`app/providers/fallback.py`); la métrica, no.

Al buscar cómo emitirla se encontró que no hay ninguna decisión pendiente solo de código: **el
mecanismo de métricas que define RFC-0010 §5 ya no es compatible con la arquitectura vigente de
la PoC.** RFC-0010 §5 titula la sección *"Métricas (namespace CloudWatch `RagCV`)"* y especifica
que se emiten con **EMF** (*Embedded Metric Format*), un formato de log JSON que **CloudWatch
Logs** interpreta para producir métricas — específico de AWS de punta a punta. Desde entonces,
ADR-0007, ADR-0008, RFC-0016, RFC-0018 y RFC-0020 sacaron AWS por completo del alcance de esta
PoC: *"ningún componente de la PoC llama a AWS"* (RFC-0018 §4). No hay ningún sistema de métricas
—CloudWatch ni ningún otro— conectado a la aplicación hoy, y `app/` no usa `structlog` ni ningún
otro logger estructurado en absoluto.

Implementar `ProviderFallbacks` ahora, dentro de RFC-0013, exige elegir entre dos caminos
igualmente equivocados: seguir RFC-0010 §5 literalmente (requeriría reintroducir AWS, contra
cuatro decisiones ya tomadas) o inventar un mecanismo de métricas propio, adelantándose a una
decisión que RFC-0010 —no RFC-0013— tiene que tomar (qué backend, qué formato, cómo se exponen).

## Decisión

Se difiere la emisión de la métrica `ProviderFallbacks` de CA-8 hasta que RFC-0010 defina un
mecanismo de métricas compatible con el alcance sin AWS de esta PoC. El `WARNING` con ambos
proveedores, ya implementado, es la evidencia operativa suficiente mientras tanto: quien opere el
sistema puede detectar una conmutación revisando los logs, aunque no exista todavía un contador
agregable.

CA-8 de RFC-0013 se corrige para reflejar esto: exige el `WARNING`, y declara la métrica como
diferida a RFC-0010 en vez de exigirla sin mecanismo que la sostenga.

## Alternativas consideradas

| Alternativa | A favor | En contra | Por qué se descarta |
| :--- | :--- | :--- | :--- |
| Implementar con CloudWatch/EMF, tal como dice RFC-0010 §5 hoy | Cumple la letra literal del RFC | Requiere reintroducir `boto3`/credenciales de AWS que ADR-0007, ADR-0008, RFC-0016, RFC-0018 y RFC-0020 ya retiraron de la PoC | Contradice cuatro decisiones ya tomadas por una sola métrica |
| Inventar un mecanismo de métricas propio dentro de RFC-0013 (p. ej. un contador en memoria, o un log con un campo `metric_name`) | Cierra CA-8 sin esperar a RFC-0010 | Adelanta una decisión de arquitectura que es de RFC-0010 (qué backend, qué formato); si RFC-0010 elige otro mecanismo, este código se reescribe o convive con dos sistemas de métricas distintos | El costo de rehacerlo supera el beneficio de cerrarlo antes de tiempo |
| **Diferir a RFC-0010, con el `WARNING` como evidencia operativa mientras tanto** (elegida) | Sin código que rehacer después; no toma ninguna decisión que no le corresponde a RFC-0013; el `WARNING` ya cubre la necesidad operativa inmediata (detectar una conmutación) | La métrica agregable (para un dashboard, una alerta automática) no existe hasta que RFC-0010 aterrice | Es la única opción que no compromete una decisión ajena ni reintroduce AWS |

## Consecuencias

**Positivas:** ningún código nuevo que mantener ni rehacer; RFC-0013 no toma una decisión de
observabilidad que no le corresponde.

**Negativas / deuda aceptada:** no hay forma automatizada de detectar una racha de conmutaciones
sin revisar logs manualmente, hasta que RFC-0010 aterrice con un mecanismo de métricas real.

**Condición de revisión:** cuando RFC-0010 se implemente (Fase 3, punto 10 del plan de ejecución)
con un mecanismo de métricas compatible con el alcance sin AWS de esta PoC, volver a CA-8 de
RFC-0013 y emitir `ProviderFallbacks` con ese mecanismo.

## Nota fuera de alcance

RFC-0010 §5 completo —no solo `ProviderFallbacks`— asume CloudWatch/EMF para sus 16 métricas.
Corregir esa sección es trabajo del propio RFC-0010 cuando le toque su turno en el plan de
ejecución (Fase 3, punto 10), no de este ADR ni de RFC-0013. Se deja anotado en RFC-0010 §5 para
que quien lo implemente no dé por buena la referencia a CloudWatch sin revisarla primero.
