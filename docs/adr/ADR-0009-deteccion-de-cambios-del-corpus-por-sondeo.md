# ADR-0009 — La detección de cambios del CV es por sondeo programado, no por eventos

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aceptada |
| **Fecha** | 2026-08-22 |
| **Modifica a** | ADR-0006 (concreta una consecuencia suya) |
| **RFCs afectados** | RFC-0019, RFC-0016, RFC-0002 |

## Contexto

El diseño documentado en `README.md` detecta los cambios del CV con la infraestructura de eventos
de AWS: S3 como fuente autoritativa, entrega a EventBridge, una regla `Object Created` que invoca
un worker dedicado, política de reintentos, DLQ y un job de reconciliación programado como
respaldo ante eventos perdidos.

Con ADR-0006 no hay S3, y con RFC-0016 §3.3 el corpus es **un fichero que vive en el VPS**, fuera
de la imagen y fuera del repositorio, para que actualizar el CV no exija un despliegue. Eso deja
un hueco concreto: **ya no existe nada que avise de que el fichero cambió.**

Conviene ver qué se pierde exactamente, porque es menos de lo que parece. De las cinco piezas del
diseño de eventos —fuente de eventos, entrega, worker, reintentos/DLQ y reconciliación—, las tres
últimas **no dependen de S3**: viven en el esquema ya desplegado (`ingestion_jobs` con
`idempotency_key` único, `attempt_count`, `job_state` incluido `dead_lettered`, y `lease_token` /
`lease_expires_at` para reclamar trabajo). Lo único que falta es **qué dispara el trabajo**.

## Decisión

**Un sondeo programado**: una tarea de `cron` en el VPS ejecuta un programa Python que comprueba
si el fichero cambió y, si cambió, registra una versión nueva en el ledger y encola su ingesta
idempotente. El contrato está en RFC-0019.

Tres propiedades hacen que esto no sea un parche, sino la opción correcta para este caso:

1. **El sondeo es su propia reconciliación.** El diseño de eventos necesitaba un job de
   reconciliación programado *porque los eventos se pierden*. Un sondeo no puede perder un evento:
   compara estado, no consume notificaciones. La pieza de respaldo desaparece porque el mecanismo
   principal ya hace su trabajo.
2. **El caso habitual cuesta un `stat`.** El sondeo no lee ni hashea el fichero salvo que su
   huella `mtime+size` haya cambiado. Con un CV que cambia unas pocas veces al año, el coste
   permanente es despreciable, y eso importa en un VPS de 2 núcleos donde la CPU ya la comparten
   PostgreSQL, la API y la inferencia de embeddings.
3. **La latencia de detección no es un requisito.** Ningún RNF exige que un cambio del CV se
   refleje en segundos. Un CV no es un flujo de eventos: es un documento que se edita de vez en
   cuando. Optimizar la reactividad aquí sería resolver un problema que nadie tiene.

## Alternativas consideradas

| Alternativa | A favor | En contra | Por qué se descarta |
| :--- | :--- | :--- | :--- |
| **Sondeo programado (`cron` + hash)** | Sin proceso de larga vida que supervisar. Imposible "perder" un cambio: compara estado. Es a la vez detección y reconciliación. Encaja en el esquema desplegado sin migración. Coste casi nulo cuando nada cambia | Latencia de detección acotada por la cadencia. Un `cron` que deja de dispararse es **invisible** si nadie lo vigila. Puede leer un fichero a medio escribir | **Elegida** |
| `inotify` / `watchdog` como demonio | Detección inmediata | Un proceso de larga vida más que supervisar y reiniciar. `inotify` **no es fiable a través de montajes bind ni en algunos sistemas de ficheros**, y pierde eventos si se desborda la cola; el resultado es un índice desactualizado sin ningún error visible. Y aun así haría falta un sondeo de respaldo — es decir, las dos cosas en vez de una | Añade un modo de fallo silencioso para ganar una latencia que ningún requisito pide |
| Reindexar solo en el despliegue | Cero mecanismo nuevo: RFC-0007 §5.3 ya reindexa en cada release | Actualizar el CV exigiría un despliegue, que es justo lo que RFC-0016 §3.3 quiso evitar al sacar el fichero de la imagen | Contradice la decisión de dónde vive el corpus. Se conserva **además** del sondeo, no en su lugar |
| Disparo manual (endpoint o comando) | Control explícito, cero automatismo | Depende de que una persona se acuerde. Un índice que no refleja el CV **no da error**: da respuestas desactualizadas con total seguridad, que es el peor modo de fallo de un sistema RAG | Se conserva como operación del runbook para forzar una reindexación, nunca como el mecanismo |
| MinIO local emulando S3 con sus eventos | Conserva el diseño de eventos tal cual y el camino de vuelta a AWS | Un servicio más, con su almacenamiento, sus credenciales y su superficie, para emular una API que en la PoC no aporta nada | Paga la complejidad de S3 sin obtener S3 |

## Consecuencias

**Positivas**

- **Desaparecen cuatro piezas** del diseño de ingesta: la regla de EventBridge, el worker
  dedicado, la DLQ de eventos y el job de reconciliación. Lo que queda es un programa que se
  ejecuta, mira y sale.
- **Sin migración de esquema.** `idempotency_key`, `lease_token`, `attempt_count` y `job_state`
  ya existen y cubren reintentos, exclusión mutua y *dead lettering*.
- **El camino de vuelta a AWS queda intacto.** Cambiar el disparador no toca el caso de uso
  idempotente: el día que vuelva S3, el evento invoca exactamente la misma lógica.
- Actualizar el CV es editar un fichero en el VPS. Sin despliegue, sin pipeline, sin ceremonia.

**Negativas / deuda aceptada**

- **Latencia de detección acotada por la cadencia**, no por el evento. Se acepta explícitamente:
  ningún RNF la exige.
- **Un `cron` que deja de dispararse no produce ningún error.** Es el modo de fallo característico
  de esta decisión y el que hay que instrumentar: RFC-0019 §7 exige un latido y una alerta por
  ausencia de comprobación. Sin eso, esta decisión cambia un fallo ruidoso por uno silencioso.
- **Lectura de un fichero a medio escribir.** Editar en el sitio con un editor que trunca y
  reescribe deja una ventana en la que el fichero es válido para `stat` pero está incompleto. Se
  contiene con la regla operativa de **reemplazo atómico** y con una comprobación de estabilidad
  (RFC-0019 §4). Es la contrapartida real de que el fichero sea editable en caliente.
- **El sondeo compite por CPU** con el resto en un host de 2 núcleos, aunque el caso habitual sea
  un `stat`. La reindexación completa, que sí cuesta, se acota con el *lease*.

## Condición de revisión

Se reabre si: (a) aparece un requisito de latencia de detección que la cadencia no cumpla;
(b) el corpus crece hasta que hashearlo en cada cambio deje de ser trivial; (c) el número de
fuentes pasa de una y el sondeo secuencial deje de escalar; o (d) el proyecto vuelve a AWS
(ADR-0006), donde el diseño de eventos de `README.md` recupera su vigencia sin reescribirse.
