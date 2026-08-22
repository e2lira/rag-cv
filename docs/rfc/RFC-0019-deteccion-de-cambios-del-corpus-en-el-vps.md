# RFC-0019 — Detección de cambios del corpus en el VPS

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aprobado |
| **Depende de** | RFC-0016, RFC-0002, RFC-0006, RFC-0010 |
| **Supersede** | El disparador de ingesta por eventos de S3 descrito en `README.md` (fuente, EventBridge, worker, DLQ y job de reconciliación), para el alcance de la PoC |
| **ADRs** | ADR-0009 |
| **Fecha** | 2026-08-22 |

---

## 1. Contexto y problema

RFC-0016 §3.3 puso el corpus en un fichero del VPS, fuera de la imagen y del repositorio, para que
actualizar el CV no exija un despliegue. ADR-0009 decidió que el disparador sea un **sondeo
programado**. Este RFC es su contrato.

Lo que ya existe y **no** se construye aquí: `ingestion_jobs` con `idempotency_key` único,
`attempt_count`, `job_state` (incluido `dead_lettered`) y `lease_token` / `lease_expires_at`;
`source_documents` con su máquina de estados, `is_current` bajo índice único parcial y el índice
no único `(object_key, content_sha256)`. **Reintentos, exclusión mutua y *dead lettering* están en
el esquema desplegado.** Lo que falta es quién y cuándo crea el trabajo.

## 2. Alcance

**Entra:** el algoritmo de detección, la comprobación de estabilidad y la regla de escritura
atómica, la exclusión mutua, la cadencia y su ejecución, el latido de observabilidad, la
configuración, y el comportamiento ante contenido repetido y ante reversiones.

**No entra:** el troceado y la normalización (RFC-0002, sin cambios), el cálculo de embeddings
(RFC-0017), el esquema (RFC-0006) y la promoción transaccional de una versión a `is_current`, que
ya define el DDL desplegado.

## 3. Algoritmo de detección

Cada ejecución del sondeo hace, en este orden y con salida temprana en cuanto puede:

```
1. stat(CORPUS_PATH)
   ├─ no existe ──> incidente: registrar, emitir métrica, SALIR SIN TOCAR EL ÍNDICE.
   │                Un fichero ausente NO significa "el CV quedó vacío".
   └─ existe: huella = f"{mtime_ns}-{size}"

2. ¿huella == s3_etag de la versión is_current?
   └─ sí ──> nada que hacer. Actualizar latido. SALIR.        (caso habitual: un stat)

3. Comprobación de estabilidad (§4): re-stat tras WATCHER_STABILITY_DELAY_SECONDS.
   └─ la huella volvió a cambiar ──> se está escribiendo. Actualizar latido. SALIR;
                                      el próximo ciclo lo recoge.

4. Leer el fichero y calcular content_sha256.

5. Registrar la versión nueva en source_documents:
      object_key      = ruta absoluta del corpus
      s3_version_id   = ULID generado ahora
      s3_etag         = huella
      content_sha256  = hash calculado
      source_metadata = {inode, mtime_ns, size, detector_version}
      ingestion_status= 'discovered'

6. Crear el trabajo en ingestion_jobs con
      idempotency_key = f"{object_key}@{s3_version_id}"
   El UNIQUE sobre idempotency_key absorbe una ejecución que muriera tras el paso 5.

7. Reclamar el trabajo por lease (§5) y ejecutar la ingesta idempotente (§6).
```

El paso 2 es el que hace barata esta decisión: con un CV que cambia unas pocas veces al año, la
inmensa mayoría de las ejecuciones terminan en un `stat` y una consulta indexada, sin leer ni
hashear nada, y sin gastar una sola llamada al proveedor de embeddings.

## 4. Estabilidad y escritura atómica

Un fichero editado **en el sitio** pasa por un estado en el que ya es visible para `stat` pero
está incompleto. Indexar ahí produce un índice con medio CV y **ningún error**.

Dos defensas, y hacen falta las dos:

**Regla operativa (normativa).** El corpus se actualiza **por reemplazo atómico**: escribir a un
temporal en el mismo sistema de ficheros y `mv` sobre el destino. `mv` dentro del mismo sistema de
ficheros es una operación atómica, así que el sondeo solo puede ver el fichero viejo completo o el
nuevo completo, nunca un estado intermedio. Va al runbook (RFC-0010) y a la documentación de
operación del VPS.

**Comprobación de estabilidad (defensa en profundidad).** Como la regla depende de que una persona
la cumpla, el paso 3 vuelve a mirar la huella tras un retardo corto y aborta si cambió. No es
infalible —una escritura lenta puede quedarse quieta justo en la ventana— pero convierte el caso
habitual de "lo edité con `nano` directamente en el servidor" en un ciclo perdido en vez de en un
índice corrupto.

Se declara sin adornos: **la comprobación de estabilidad reduce el riesgo, no lo elimina.** Lo que
lo elimina es el reemplazo atómico. Por eso la regla es normativa y no una recomendación.

## 5. Exclusión mutua

Dos ejecuciones del sondeo pueden solaparse si una tarda más que la cadencia, y el despliegue de
RFC-0007 §5.3 también indexa. Nada de eso puede producir dos ingestas simultáneas.

El mecanismo ya está en el esquema: se reclama el trabajo escribiendo `lease_token` y
`lease_expires_at` en una transacción, y solo el titular del *lease* muta el estado. El índice
`ingestion_jobs_claim_idx` sobre `(job_state, lease_expires_at, created_at)` existe exactamente
para esa consulta.

Un *lease* **caducado es reclamable**: es lo que permite recuperarse de una ejecución que murió a
mitad. Por eso `WATCHER_LEASE_SECONDS` debe superar con margen la duración de una reindexación
completa; si se queda corto, un segundo proceso reclama trabajo que aún está en curso.

## 6. Contenido repetido y reversiones — la trampa

`README.md` dice que *"un hash ya indexado se resuelve como trabajo idempotente sin regenerar
embeddings"*. Aplicado literalmente, ese enunciado introduce un fallo grave, y este RFC lo acota.

Al promover una versión, el DDL **elimina los embeddings de la anterior**:

```sql
-- retire the old current source (which removes its vectors); promote the successor;
```

Entonces:

| Caso | `content_sha256` coincide con… | Comportamiento correcto |
| :--- | :--- | :--- |
| Reescritura sin cambios reales (`touch`, guardado idéntico) | la versión **`is_current`** | Registrar la versión nueva y **no regenerar embeddings**: los vectores vigentes ya corresponden a ese contenido |
| **Reversión** a un CV anterior | una versión **`superseded`** | **Regenerar embeddings.** Sus vectores fueron eliminados al promoverse la que la sucedió |

Saltarse el segundo caso deja el índice **vacío para la versión promovida**: el sistema respondería
"no encuentro nada en el CV" con total seguridad, que es exactamente el modo de fallo que un RAG no
puede permitirse. La comprobación no es "¿existe este hash en el ledger?" sino **"¿es este hash el
de la versión actualmente indexada?"**.

## 7. Cadencia, ejecución y latido

**Cadencia por defecto: cada 5 minutos.** Un CV se edita de vez en cuando; 5 minutos acotan el
desfase a un coste permanente despreciable.

Se instala en el **crontab de `qrimapp-reto`**, no en `/etc/cron.d`. Hay acceso de administrador
en el VPS, pero **la operación diaria no lo usa** (RFC-0016 §8.1), y el sondeo es la operación
diaria por excelencia: se ejecuta cada cinco minutos, sin nadie mirando.

Un `crontab` de usuario cumple la misma función, sobrevive a los reinicios igual y —lo que
importa— **no obliga a que exista un `sudo` sin contraseña** para una automatización que corre
sola. Esa es la forma habitual en que un `NOPASSWD` acaba instalado y olvidado en un host.

```cron
# crontab -e  (usuario qrimapp-reto)
RAG_CV_HOME=/home/qrimapp-reto/rag-cv

*/5 * * * * cd $RAG_CV_HOME/current && \
  $RAG_CV_HOME/current/.venv/bin/python -m app.ingestion.watcher \
  >> $RAG_CV_HOME/logs/watcher.log 2>&1

# rotación en espacio de usuario: no se toca /etc/logrotate.d, que exigiría root
0 4 * * * /usr/sbin/logrotate --state $RAG_CV_HOME/logs/.logrotate.state \
  $RAG_CV_HOME/logs/logrotate.conf
```

Se invoca el intérprete del entorno virtual de la **release activa**, no un `python` del sistema:
`current` es un enlace simbólico que el despliegue conmuta de forma atómica (RFC-0020 §6), así que
el sondeo pasa a ejecutar la release nueva sin tocar el `crontab`.

`RAG_CV_HOME` es una asignación
del propio `crontab`, no un comentario: `cron` la coloca en el entorno del proceso hijo y es `sh`
quien la expande al ejecutar la orden. Escrita como comentario, la ruta quedaría vacía y el `cd`
llevaría al directorio personal — un fallo que solo se ve leyendo la bitácora.

**La bitácora necesita rotación explícita.** Sin contenedores no hay controlador de registro que
ponga un techo (ADR-0010), y nada acota la salida que el
`cron` redirige a fichero: el proceso escribe a `stdout`, y ese `stdout` acaba en
`watcher.log`. Sin rotación, un fallo que se repita cada 5 minutos llena el disco de la cuenta, y
un disco lleno hace fallar el propio sondeo — el fallo silencioso de §7, otra vez, por la puerta
de atrás.

**El latido no es opcional, es la mitad de esta decisión.** Un `cron` que deja de dispararse
—porque alguien lo comentó, porque el servicio de `cron` murió, porque el disco se llenó y el
la ejecución falla— **no produce ningún error**. El síntoma es un índice desactualizado
que responde con seguridad, y puede pasar semanas sin que nadie lo note.

Por eso toda ejecución, **incluida la que no encuentra cambios**, registra un latido con su
instante y su resultado, y se alerta si la última comprobación con éxito es más antigua que
`WATCHER_HEARTBEAT_MAX_AGE_SECONDS` (por defecto, tres veces la cadencia). La alerta va al canal
de RFC-0010, igual que el resto.

## 8. Configuración

| Variable | Por defecto | Descripción |
| :--- | :--- | :--- |
| `CORPUS_PATH` | `$RAG_CV_HOME/corpus/cv.md` | Ruta absoluta del corpus en el VPS (RFC-0001, RFC-0016 §8.1) |
| `WATCHER_CADENCE` | `*/5 * * * *` | Cadencia del `cron`; no la lee la aplicación, se documenta aquí para que viva junto al resto |
| `WATCHER_STABILITY_DELAY_SECONDS` | `5` | Retardo de la comprobación de estabilidad (§4) |
| `WATCHER_LEASE_SECONDS` | `600` | Duración del *lease*. **Debe** superar una reindexación completa (§5) |
| `WATCHER_MAX_ATTEMPTS` | `5` | Intentos antes de `dead_lettered` |
| `WATCHER_HEARTBEAT_MAX_AGE_SECONDS` | `900` | Edad máxima del último latido con éxito antes de alertar (§7) |

## 9. Fallos y degradación

| Fallo | Detección | Comportamiento |
| :--- | :--- | :--- |
| El fichero no existe | Paso 1 | Incidente registrado y métrica. **El índice vigente no se toca** |
| Fichero a medio escribir | Paso 3 | Se aborta el ciclo; el siguiente lo recoge |
| El `cron` deja de dispararse | Latido caducado (§7) | Alerta por ausencia de comprobación |
| Ejecución muerta a mitad | *Lease* caducado | La siguiente ejecución reclama el trabajo y reintenta |
| Fallo del embedder durante la ingesta | RFC-0017 §9 | `rollback` completo. El trabajo queda `failed` y se reintenta |
| Superados `WATCHER_MAX_ATTEMPTS` | `attempt_count` | `dead_lettered` + alerta. **No se reintenta en bucle** |
| Dos ejecuciones solapadas | *Lease* | La segunda no encuentra trabajo reclamable y sale |
| Fichero corrupto o vacío que sí es estable | Validación de RFC-0002 | La ingesta falla y hace `rollback`: nunca se promueve un índice vacío |
| Disco lleno | La ejecución falla al escribir | El latido no se actualiza ⇒ alerta (§7) |
| Bitácora sin rotar llenando la cuenta | Rotación diaria en espacio de usuario (§7) | Sin ella, un fallo repetido cada 5 min llena el disco y tumba el propio sondeo |

## 10. Criterios de aceptación

| # | Criterio | Verificación |
| :--- | :--- | :--- |
| CA-1 | Sin cambios en el fichero, la ejecución no lee ni hashea el corpus y termina tras el `stat` y una consulta | `test_watcher.py::test_no_change_short_circuits` (espía de E/S) |
| CA-2 | Un cambio de contenido produce una versión nueva, su trabajo, y un índice que refleja el contenido nuevo | Prueba de integración de extremo a extremo |
| CA-3 | Una reescritura con contenido idéntico al `is_current` registra versión y **no** regenera embeddings | `test_watcher.py::test_identical_content_skips_embedding` |
| CA-4 | **Una reversión a un contenido `superseded` SÍ regenera embeddings** y deja el índice consultable | `test_watcher.py::test_revert_reindexes` |
| CA-5 | Un fichero que cambia durante la comprobación de estabilidad no se indexa en ese ciclo | `test_watcher.py::test_unstable_file_skipped` |
| CA-6 | Dos ejecuciones concurrentes producen una sola ingesta | `test_watcher.py::test_concurrent_runs_single_ingestion` |
| CA-7 | Un *lease* caducado por una ejecución muerta se reclama y el trabajo se completa | `test_watcher.py::test_expired_lease_reclaimed` |
| CA-8 | Revertir el CV no viola ninguna restricción de unicidad del ledger | CA-4 + consulta a `source_documents` |
| CA-9 | Un corpus ausente no modifica el índice vigente y emite incidente | `test_watcher.py::test_missing_corpus_is_incident` |
| CA-10 | Toda ejecución, incluidas las que no hallan cambios, actualiza el latido | `test_watcher.py::test_heartbeat_always_updated` |
| CA-11 | Un latido más antiguo que el umbral dispara alerta | Prueba de la regla de alerta (RFC-0010) |
| CA-12 | Superar `WATCHER_MAX_ATTEMPTS` deja el trabajo `dead_lettered` y no reintenta | `test_watcher.py::test_dead_letter` |
| CA-13 | El fallo del embedder deja el índice intacto, nunca a medias | `test_watcher.py::test_rollback_on_failure` |
| CA-14 | El sondeo está en el `crontab` del usuario y se ejecuta sin `sudo` | `crontab -l` + latido tras un ciclo |
| CA-15 | La bitácora rota y no crece sin límite | Ejecución de la rotación + `ls -l` sobre `logs/` |

## 11. Riesgos

| Riesgo | Mitigación |
| :--- | :--- |
| **El `cron` deja de dispararse y nadie lo nota** | Latido en cada ejecución + alerta por ausencia (§7, CA-10, CA-11). Es el riesgo principal de ADR-0009 |
| Una reversión deja el índice vacío | §6 + CA-4: la comparación es contra la versión **actual**, no contra el historial |
| Indexar un fichero a medio escribir | Reemplazo atómico normativo + comprobación de estabilidad (§4, CA-5) |
| `WATCHER_LEASE_SECONDS` menor que una reindexación ⇒ dos procesos sobre el mismo trabajo | §5 lo declara como condición; se ajusta con la medición de RFC-0017 CA-5 |
| Reintentos en bucle consumiendo CPU del host | `WATCHER_MAX_ATTEMPTS` y `dead_lettered` (CA-12) |
| Alguien borra el corpus y el sistema "se vacía" | §3 paso 1 y CA-9: ausencia es incidente, no contenido vacío |
| El sondeo coincide con tráfico y degrada la latencia | Cadencia baja + *lease*; se mide en RFC-0016 CA-4 |
| La bitácora llena el disco y tumba el sondeo que debía vigilar | Rotación en espacio de usuario (§7, CA-15) |

## Contrato de auditoría (gate ADU)

| # | Comprobación | Cómo se verifica | Severidad si falla |
| :--- | :--- | :--- | :--- |
| A-1 | La decisión de regenerar embeddings compara contra la versión `is_current`, no contra el historial | CA-3, CA-4 | **Bloqueante** |
| A-2 | Existe latido en toda ejecución y alerta por ausencia de comprobación | CA-10, CA-11 | **Bloqueante** |
| A-3 | La ingesta se reclama por *lease* antes de mutar estado | CA-6, CA-7 | Bloqueante |
| A-4 | Un fallo durante la ingesta hace `rollback` completo | CA-13 | Bloqueante |
| A-5 | Un corpus ausente no retira ni vacía el índice vigente | CA-9 | Bloqueante |
| A-6 | El camino sin cambios no lee ni hashea el fichero | CA-1 | Mayor |
| A-7 | La comprobación de estabilidad existe y aborta el ciclo | CA-5 | Mayor |
| A-8 | La regla de reemplazo atómico está en el runbook de RFC-0010 | Lectura | Mayor |
| A-9 | `WATCHER_MAX_ATTEMPTS` termina en `dead_lettered` con alerta | CA-12 | Mayor |
| A-10 | El `idempotency_key` es determinista a partir de `object_key` y del token de versión | Lectura + CA-6 | Mayor |
| A-11 | No se introdujo ninguna tabla ni columna nueva para el sondeo | `git diff` sobre `infra/sql/` | Menor |
| A-12 | El sondeo se instala y se ejecuta sin `sudo`, y no existe ninguna regla `NOPASSWD` para sostenerlo | CA-14 | Mayor |
| A-13 | La bitácora del sondeo tiene rotación configurada | CA-15 | Mayor |
