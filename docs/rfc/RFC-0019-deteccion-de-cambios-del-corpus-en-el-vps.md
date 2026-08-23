# RFC-0019 — Detección de cambios del corpus en el VPS

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aprobado |
| **Depende de** | RFC-0016, RFC-0002, RFC-0006 |
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
no único `(object_key, content_sha256)`. **Las restricciones que hacen posibles los reintentos, la
exclusión mutua y el *dead lettering* están en el esquema desplegado.**

**Lo que no está, y este RFC creía que sí.** La versión anterior de §1 y §2 daba por construida la
promoción transaccional de una versión a `is_current`. No lo está. El DDL define el **invariante**
—`idx_source_one_current` y `ck_source_current`— y RFC-0006 §4.5 lo dice con la palabra exacta: el
índice *«**permite** que la promoción de una versión nueva y la degradación de la anterior ocurran
en la misma transacción»*. Permitir no es implementar. No hay disparador, no hay función, y
ninguna línea de `app/` menciona `source_documents`, `is_current` ni promoción alguna.

Tampoco existe `ingestion_jobs_claim_idx`, que §5 daba por hecho: sobre `ingestion_jobs` no hay más
índices que los implícitos de la clave primaria y de las dos restricciones `UNIQUE`.

Así que lo que falta es más de lo que decía: **quién crea el trabajo, quién promueve la versión, y
el índice sobre el que se reclama.** Las tres cosas entran aquí.

## 2. Alcance

**Entra:** el algoritmo de detección, la comprobación de estabilidad y la regla de escritura
atómica, la exclusión mutua, **la promoción transaccional de una versión a `is_current` y la
degradación de la anterior**, el **registro** del latido y la tabla que lo sostiene, el índice de
reclamación, la configuración, y el comportamiento ante contenido repetido y ante reversiones.

**No entra:** el troceado y la normalización (RFC-0002, sin cambios), el cálculo de embeddings
(RFC-0017), el resto del esquema (RFC-0006), **la regla de alerta sobre el latido y el runbook**
(RFC-0010, punto 13 del plan), y **la instalación del `cron` y de la rotación de bitácoras**
(RFC-0020, punto 11). Este RFC *escribe* el latido; *alertar* por su ausencia es de RFC-0010.

> **Por qué la frontera se movió.** La versión anterior situaba la alerta, el runbook, el
> `crontab` y la rotación dentro de los criterios de este RFC, y con ellos seis comprobaciones del
> gate —CA-11, CA-14, CA-15, A-8, A-12 y A-13— que **no se pueden ejecutar en el punto 5**: exigen
> el canal de alerta de RFC-0010 (punto 13) y un VPS aprovisionado por RFC-0020 (punto 11),
> mientras DEV es Windows. Un criterio Bloqueante que nadie puede verificar no endurece el gate:
> lo bloquea. Cada uno pasa al RFC que lo construye, y este conserva lo que sí produce.

## 3. Algoritmo de detección

Cada ejecución del sondeo hace, en este orden y con salida temprana en cuanto puede:

```
1. stat(CORPUS_PATH)
   ├─ no existe ──> incidente: registrar, emitir métrica, SALIR SIN TOCAR EL ÍNDICE.
   │                Un fichero ausente NO significa "el CV quedó vacío".
   └─ existe: huella = f"{mtime_ns}-{size}"

2. ¿huella == source_fingerprint de la versión is_current?
   └─ sí ──> nada que hacer. Actualizar latido. SALIR.        (caso habitual: un stat)

3. Comprobación de estabilidad (§4): re-stat tras WATCHER_STABILITY_DELAY_SECONDS.
   └─ la huella volvió a cambiar ──> se está escribiendo. Actualizar latido. SALIR;
                                      el próximo ciclo lo recoge.

4. Leer el fichero y calcular content_sha256.

5. Registrar la versión nueva en source_documents:
      object_key         = ruta absoluta del corpus
      source_version_id  = ULID generado ahora
      source_fingerprint = huella
      content_sha256     = hash calculado
      source_metadata    = {inode, mtime_ns, size, detector_version}
      ingestion_status   = 'discovered'

6. Crear el trabajo en ingestion_jobs con
      idempotency_key = f"{object_key}@{source_version_id}"
   El UNIQUE sobre idempotency_key absorbe una ejecución que muriera tras el paso 5.

7. Reclamar el trabajo por lease (§5) y ejecutar la ingesta idempotente (§6).

8. Promover la versión en UNA transacción (§6.1):
      version nueva  -> ingestion_status='indexed', is_current=true, indexed_at=now()
      version previa -> ingestion_status='superseded', is_current=false
   El orden importa: ck_source_current exige 'indexed' ANTES de is_current=true,
   e idx_source_one_current prohibe dos vigentes a la vez -> se degrada la
   anterior y se promueve la nueva sin soltar la transaccion.

9. Actualizar el latido (§7). SALIR.
```

**Los nombres de columna son los del esquema desplegado.** RFC-0006 §4.5 renombró `s3_version_id`
y `s3_etag` a `source_version_id` y `source_fingerprint` al desaparecer S3, y declaró la
equivalencia «para §5». El pseudocódigo de esta sección seguía usando los nombres viejos, que es
justo donde un Desarrollador los copiaría.

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
RFC-0020 §6 también indexa. Nada de eso puede producir dos ingestas simultáneas.

Las **columnas** del mecanismo ya están en el esquema: se reclama el trabajo escribiendo
`lease_token` y `lease_expires_at` en una transacción, y solo el titular del *lease* muta el
estado. El `CHECK ck_lease` garantiza que las dos se escriban juntas o ninguna.

**El índice de reclamación hay que crearlo**, en una migración de este RFC:

```sql
CREATE INDEX ingestion_jobs_claim_idx
    ON ingestion_jobs (job_state, lease_expires_at, created_at);
```

La versión anterior de esta sección afirmaba que ese índice *«existe exactamente para esa
consulta»*. No existe: sobre `ingestion_jobs` no hay más índices que los implícitos de la clave
primaria y de `uq_job_idempotency` y `uq_job_object_version`. Sin él, la consulta de reclamación
hace un recorrido secuencial — irrelevante con una decena de filas, y una trampa el día que el
ledger crezca.

Un *lease* **caducado es reclamable**: es lo que permite recuperarse de una ejecución que murió a
mitad. Por eso `WATCHER_LEASE_SECONDS` debe superar con margen la duración de una reindexación
completa; si se queda corto, un segundo proceso reclama trabajo que aún está en curso.

## 6. Contenido repetido y reversiones

`README.md` dice que *"un hash ya indexado se resuelve como trabajo idempotente sin regenerar
embeddings"*. Aplicado literalmente, ese enunciado introduce un fallo grave, y esta sección lo
acota. Pero la versión anterior lo acotaba **con un motivo falso**, y conviene decir cuál era.

**Lo que esta sección afirmaba y no es cierto.** Decía que *«al promover una versión, el DDL
elimina los embeddings de la anterior»*, y citaba un comentario SQL que no existe en ninguna parte
del repositorio. No puede existir: `cv_chunks` **no tiene ninguna columna ni clave foránea hacia
`source_documents`**. Hay un solo juego de fragmentos por `doc_id`, sobrescrito en sitio. Promover
una versión no borra vectores porque no hay vectores atados a una versión.

**Lo que sí es cierto es la conclusión.** Una reversión tiene que regenerar embeddings. Lo que
cambia es quién lo garantiza:

| Caso | `content_sha256` coincide con… | Qué hace el sondeo |
| :--- | :--- | :--- |
| Reescritura sin cambios reales (`touch`, guardado idéntico) | la versión **`is_current`** | Actualiza `source_fingerprint` de la fila vigente y sale. **No** registra versión nueva, **no** crea trabajo, **no** embebe |
| **Reversión** a un CV anterior | una versión **`superseded`** | Ciclo completo: versión nueva, trabajo, ingesta, promoción |
| Contenido nunca visto | ninguna | Ciclo completo |

**La decisión de re-embeber no se toma aquí.** `index_corpus` (RFC-0002) compara el
`content_hash` de cada fragmento contra lo que hay en `cv_chunks` y solo embebe lo que difiere:

- contenido idéntico ⇒ todos los fragmentos salen `unchanged`, `to_embed` queda vacío y no se
  hace **ninguna** llamada al proveedor;
- reversión ⇒ los `content_hash` difieren de los vigentes, salen `updated`, y se re-embeben.

Es decir: el comportamiento que esta sección exige **ya lo produce el indexador**, sin consultar
el ledger. Delegarlo ahí no es comodidad, es correcto — el indexador compara contra lo que
realmente está indexado, mientras que el ledger dice lo que *debería* estarlo. Si los dos
discrepan, el que acierta es el indexador, y la discrepancia se cura sola en el siguiente ciclo.

**Para qué sirve entonces la comparación contra `is_current`.** Para el **atajo del paso 2**: no
leer ni hashear un fichero de decenas de kilobytes cinco veces por hora. Es una decisión de coste,
no de corrección. Confundir las dos —que es lo que hacía la versión anterior— lleva a escribir en
el sondeo una lógica de regeneración que duplica la del indexador y que puede contradecirla.

Y hay un caso que la fila 1 resuelve y la versión anterior no veía: un `touch` cambia el `mtime`,
así que la huella deja de coincidir y el paso 2 no ataja. Registrar una versión nueva por cada
`touch` haría crecer el ledger sin que el corpus cambie. Actualizar la huella de la fila vigente
deja el atajo operativo desde el ciclo siguiente.

### 6.1 Promoción y degradación (normativo)

El paso 8 del algoritmo ocurre **en una sola transacción**, y el orden lo imponen dos
restricciones del esquema desplegado:

```sql
CONSTRAINT ck_source_current CHECK (NOT is_current OR ingestion_status = 'indexed')
CREATE UNIQUE INDEX idx_source_one_current ON source_documents (object_key) WHERE is_current;
```

La primera prohíbe marcar vigente una versión que no esté `indexed`. La segunda prohíbe que
convivan dos vigentes para el mismo `object_key`. Por eso:

1. degradar la vigente — `ingestion_status='superseded'`, `is_current=false`;
2. marcar la nueva `ingestion_status='indexed'` y `indexed_at=now()`;
3. marcar la nueva `is_current=true`.

Los tres pasos, la misma transacción. Si se hacen en dos, existe un instante en que el corpus no
tiene versión vigente y el paso 2 del ciclo siguiente no encuentra contra qué comparar.

**Esto es trabajo de este RFC, no del esquema.** RFC-0006 §4.5 dice que el índice parcial
*«**permite** que la promoción de una versión nueva y la degradación de la anterior ocurran en la
misma transacción»*. Permite no es implementa: el DDL aporta el invariante, y quien lo respeta es
el código que este RFC define. La versión anterior de §2 daba la promoción por construida y la
excluía del alcance — dejando fuera el único paso que cierra el bucle de §3.

## 7. Cadencia, ejecución y latido

**Cadencia por defecto: cada 5 minutos.** Un CV se edita de vez en cuando; 5 minutos acotan el
desfase a un coste permanente despreciable.

Se instala en el **crontab de `qrimapp-reto`**, no en `/etc/cron.d`. Hay acceso de administrador
en el VPS, pero **la operación diaria no lo usa** (RFC-0016 §8.1), y el sondeo es la operación
diaria por excelencia: se ejecuta cada cinco minutos, sin nadie mirando.

Un `crontab` de usuario cumple la misma función, sobrevive a los reinicios igual y —lo que
importa— **no obliga a que exista un `sudo` sin contraseña** para una automatización que corre
sola. Esa es la forma habitual en que un `NOPASSWD` acaba instalado y olvidado en un host.

El bloque siguiente es **el contrato de lo que RFC-0020 debe instalar** durante el
aprovisionamiento (punto 11 del plan), no un paso que se ejecute en el punto 5:

```cron
# crontab -e  (usuario qrimapp-reto)
RAG_CV_HOME=/opt/rag-cv

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
—porque alguien lo comentó, porque el servicio de `cron` murió, porque el disco se llenó y la
ejecución falla— **no produce ningún error**. El síntoma es un índice desactualizado que responde
con seguridad, y puede pasar semanas sin que nadie lo note.

Por eso toda ejecución, **incluida la que no encuentra cambios**, registra un latido con su
instante y su resultado.

### 7.1 Dónde vive el latido (normativo)

El latido necesita sobrevivir al proceso que lo escribe, y no tenía dónde: la versión anterior de
este RFC lo exigía como Bloqueante (A-2), excluía el esquema del alcance (§2) y prohibía cualquier
tabla nueva (A-11). Tres cláusulas incompatibles.

Se resuelve con una tabla de una sola fila, en una migración de este RFC:

```sql
CREATE TABLE watcher_heartbeat (
    object_key      TEXT        PRIMARY KEY,
    last_run_at     TIMESTAMPTZ NOT NULL,
    last_success_at TIMESTAMPTZ,
    last_outcome    TEXT        NOT NULL,
    detail          JSONB       NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ck_watcher_outcome CHECK (
        last_outcome IN ('no_change','indexed','unstable','missing_corpus','failed')
    )
);
```

`last_run_at` se escribe **siempre**; `last_success_at` solo cuando el ciclo termina bien. La
alerta de §7.2 mira `last_success_at`, no `last_run_at`: un sondeo que se dispara puntualmente y
falla en todos los intentos es exactamente igual de grave que uno que no se dispara, y mirando
solo `last_run_at` parecería sano.

> **Por qué una tabla y no un fichero.** Un fichero no exige migración y sigue funcionando con la
> base caída, que es su único argumento de peso. Pierde en todo lo demás: la regla de alerta de
> RFC-0010 es una consulta, el latido es transaccional con la promoción que lo justifica, y el
> estado del sistema deja de estar repartido en dos sitios con reglas de respaldo distintas. Y el
> caso «base caída» no queda desatendido: sin base no hay `last_success_at` nuevo, el umbral vence
> y la alerta salta — que es la reacción correcta, porque un sondeo que no puede escribir tampoco
> puede indexar.

**A-11 se reformula en consecuencia.** Lo que esa comprobación protegía era el ledger: que nadie
levantara un registro paralelo al de RFC-0006 en vez de usar el que existe. Esa protección sigue.
Lo que no puede seguir es leerse como «ninguna tabla, nunca», porque entonces prohíbe el
mecanismo que A-2 declara obligatorio.

### 7.2 Lo que este RFC no hace: alertar

Se alerta si `last_success_at` es más antiguo que `WATCHER_HEARTBEAT_MAX_AGE_SECONDS` (por
defecto, tres veces la cadencia). **Esa regla es de RFC-0010**, punto 13 del plan, junto con el
resto de alarmas y el runbook.

Aquí se declara el contrato que RFC-0010 consumirá —la tabla, el significado de cada columna y el
umbral— y nada más. La versión anterior incluía la alerta entre sus propios criterios (CA-11,
A-2), lo que dejaba el gate de un RFC del punto 5 dependiendo de infraestructura del punto 13.

## 8. Configuración

| Variable | Por defecto | Descripción |
| :--- | :--- | :--- |
| `CORPUS_PATH` | `corpus/cv.md` en DEV · `$RAG_CV_HOME/corpus/cv.md` en QA | Ya existe en `Settings` desde RFC-0002. **El valor por defecto del código es el relativo**; el absoluto lo fija el `.env` del VPS (RFC-0020 §8) |
| `WATCHER_CADENCE` | `*/5 * * * *` | Cadencia del `cron`; no la lee la aplicación, se documenta aquí para que viva junto al resto |
| `WATCHER_STABILITY_DELAY_SECONDS` | `5` | Retardo de la comprobación de estabilidad (§4) |
| `WATCHER_LEASE_SECONDS` | `600` | Duración del *lease*. **Debe** superar una reindexación completa (§5) |
| `WATCHER_MAX_ATTEMPTS` | `5` | Intentos antes de `dead_lettered` |
| `WATCHER_HEARTBEAT_MAX_AGE_SECONDS` | `900` | Edad máxima de `last_success_at` antes de alertar (§7.2). **La declara este RFC; la consume RFC-0010** |

**Dependencia nueva.** El paso 5 genera un ULID para `source_version_id` (RFC-0006 §4.5) y no hay
librería ULID en el proyecto. Se añade `python-ulid` a `pyproject.toml`; el Informe de
Implementación la declara como desviación de alcance si se resuelve de otra forma.

**`CORPUS_PATH` no se redeclara.** RFC-0002 ya la puso en `Settings` y en `.env.example`. Este RFC
la usa; las cinco `WATCHER_*` sí son nuevas y van a los dos sitios (ADU-PROCESO §5).

## 9. Fallos y degradación

| Fallo | Detección | Comportamiento |
| :--- | :--- | :--- |
| El fichero no existe | Paso 1 | Incidente registrado y métrica. **El índice vigente no se toca** |
| Fichero a medio escribir | Paso 3 | Se aborta el ciclo; el siguiente lo recoge |
| El `cron` deja de dispararse | `last_success_at` caducado (§7.1) | Alerta por ausencia de comprobación — regla de RFC-0010 |
| Ejecución muerta a mitad | *Lease* caducado | La siguiente ejecución reclama el trabajo y reintenta |
| Fallo del embedder durante la ingesta | RFC-0017 §9 | `rollback` completo. El trabajo queda `failed` y se reintenta |
| Superados `WATCHER_MAX_ATTEMPTS` | `attempt_count` | `dead_lettered` + alerta. **No se reintenta en bucle** |
| Dos ejecuciones solapadas | *Lease* | La segunda no encuentra trabajo reclamable y sale |
| Fichero corrupto o vacío que sí es estable | Validación de RFC-0002 | La ingesta falla y hace `rollback`: nunca se promueve un índice vacío |
| Disco lleno | La ejecución falla al escribir | `last_success_at` no se actualiza ⇒ alerta (§7.1) |
| Bitácora sin rotar llenando la cuenta | Rotación diaria en espacio de usuario (§7), instalada por RFC-0020 | Sin ella, un fallo repetido cada 5 min llena el disco y tumba el propio sondeo |

## 10. Criterios de aceptación

| # | Criterio | Verificación |
| :--- | :--- | :--- |
| CA-1 | Sin cambios en el fichero, la ejecución no lee ni hashea el corpus y termina tras el `stat` y una consulta | `test_watcher.py::test_no_change_short_circuits` (espía de E/S) |
| CA-2 | Un cambio de contenido produce una versión nueva, su trabajo, y un índice que refleja el contenido nuevo | Prueba de integración de extremo a extremo |
| CA-3 | Una reescritura con contenido idéntico al `is_current` **no** regenera embeddings: ningún fragmento cambia de `content_hash` y el embebedor no se llama ni una vez | `test_watcher.py::test_identical_content_skips_embedding` |
| CA-4 | **Una reversión a un contenido `superseded` SÍ regenera embeddings** y deja el índice consultable | `test_watcher.py::test_revert_reindexes` |
| CA-5 | Un fichero que cambia durante la comprobación de estabilidad no se indexa en ese ciclo | `test_watcher.py::test_unstable_file_skipped` |
| CA-6 | Dos ejecuciones concurrentes producen una sola ingesta | `test_watcher.py::test_concurrent_runs_single_ingestion` |
| CA-7 | Un *lease* caducado por una ejecución muerta se reclama y el trabajo se completa | `test_watcher.py::test_expired_lease_reclaimed` |
| CA-8 | Revertir el CV no viola ninguna restricción de unicidad del ledger | CA-4 + consulta a `source_documents` |
| CA-9 | Un corpus ausente no modifica el índice vigente y emite incidente | `test_watcher.py::test_missing_corpus_is_incident` |
| CA-10 | Toda ejecución, incluidas las que no hallan cambios, actualiza el latido | `test_watcher.py::test_heartbeat_always_updated` |
| CA-12 | Superar `WATCHER_MAX_ATTEMPTS` deja el trabajo `dead_lettered` y no reintenta | `test_watcher.py::test_dead_letter` |
| CA-13 | El fallo del embedder deja el índice intacto, nunca a medias | `test_watcher.py::test_rollback_on_failure` |
| CA-16 | La promoción deja exactamente una versión `is_current` con `ingestion_status='indexed'`, y la anterior `superseded` | `test_watcher.py::test_promotion_single_current` |
| CA-17 | Un `touch` sin cambio de contenido actualiza `source_fingerprint` de la fila vigente y **no** registra versión nueva ni llama al embebedor | `test_watcher.py::test_touch_updates_fingerprint_only` |
| CA-18 | Toda ejecución escribe `last_run_at`; solo el ciclo completo escribe `last_success_at` | `test_watcher.py::test_heartbeat_success_vs_run` |

**CA-3 decía «registra versión y no regenera embeddings», y contradecía a §6 y a CA-17.** Los
tres describen el mismo escenario —una reescritura con contenido idéntico al `is_current`— y §6
fila 1 lo resuelve sin registrar fila nueva: hacerlo engordaría el ledger sin que el corpus
cambie, y obligaría a un ciclo promover/degradar entre dos versiones de contenido idéntico. El
defecto lo introdujo el propio DoR (PR #56), que reescribió §6 y añadió CA-17 sin tocar el texto
de CA-3. CA-3 conserva lo que de verdad aporta frente a CA-17: que el proveedor de embeddings no
se llama.

**Los huecos 11, 14 y 15 son deliberados.** Esos criterios se movieron al RFC que construye lo que
verifican —la alerta a RFC-0010, el `crontab` y la rotación a RFC-0020— y se conserva su número
para que las referencias existentes no apunten a otra cosa (§2).

## 11. Riesgos

| Riesgo | Mitigación |
| :--- | :--- |
| **El `cron` deja de dispararse y nadie lo nota** | Latido en cada ejecución (§7.1, CA-10, CA-18) + alerta por ausencia, que construye RFC-0010 (§7.2). Es el riesgo principal de ADR-0009, y **este RFC solo cubre la mitad**: sin la alerta de RFC-0010 el latido se escribe y nadie lo mira |
| Una reversión deja el índice vacío | §6 + CA-4: la comparación es contra la versión **actual**, no contra el historial |
| Indexar un fichero a medio escribir | Reemplazo atómico normativo + comprobación de estabilidad (§4, CA-5) |
| `WATCHER_LEASE_SECONDS` menor que una reindexación ⇒ dos procesos sobre el mismo trabajo | §5 lo declara como condición; se ajusta con la medición de RFC-0017 CA-5 |
| Reintentos en bucle consumiendo CPU del host | `WATCHER_MAX_ATTEMPTS` y `dead_lettered` (CA-12) |
| Alguien borra el corpus y el sistema "se vacía" | §3 paso 1 y CA-9: ausencia es incidente, no contenido vacío |
| El sondeo coincide con tráfico y degrada la latencia | Cadencia baja + *lease*; se mide en RFC-0016 CA-4 |
| La bitácora llena el disco y tumba el sondeo que debía vigilar | Rotación en espacio de usuario, que instala RFC-0020 (§7). **Riesgo abierto entre el punto 5 y el punto 11** |

## Contrato de auditoría (gate ADU)

| # | Comprobación | Cómo se verifica | Severidad si falla |
| :--- | :--- | :--- | :--- |
| A-1 | Una reversión a contenido `superseded` deja el índice consultable, y una reescritura idéntica no gasta ninguna llamada al proveedor | CA-3, CA-4 | **Bloqueante** |
| A-1b | El sondeo **no** duplica la decisión de re-embeber: delega en `index_corpus` y usa el ledger solo para el atajo del paso 2 | Lectura del código + CA-17 | Mayor |
| A-2 | Existe latido en toda ejecución, con `last_run_at` y `last_success_at` diferenciados | CA-10, CA-18 | **Bloqueante** |
| A-3 | La ingesta se reclama por *lease* antes de mutar estado | CA-6, CA-7 | Bloqueante |
| A-4 | Un fallo durante la ingesta hace `rollback` completo | CA-13 | Bloqueante |
| A-5 | Un corpus ausente no retira ni vacía el índice vigente | CA-9 | Bloqueante |
| A-6 | El camino sin cambios no lee ni hashea el fichero | CA-1 | Mayor |
| A-7 | La comprobación de estabilidad existe y aborta el ciclo | CA-5 | Mayor |
| A-9 | `WATCHER_MAX_ATTEMPTS` termina en `dead_lettered` con alerta | CA-12 | Mayor |
| A-10 | El `idempotency_key` es determinista a partir de `object_key` y del token de versión | Lectura + CA-6 | Mayor |
| A-11 | No se levantó ningún registro paralelo al ledger de RFC-0006. La única tabla nueva es `watcher_heartbeat` (§7.1), y va en una migración Alembic | `git diff` sobre `migrations/` — el esquema vive en Alembic desde RFC-0006 §2.2, que **retiró** `infra/sql/` | Mayor |
| A-14 | La promoción y la degradación ocurren en **una** transacción, en el orden que imponen `ck_source_current` e `idx_source_one_current` | CA-16 + lectura | **Bloqueante** |
| A-15 | Existe el índice de reclamación `ingestion_jobs_claim_idx` | `\di` sobre `ingestion_jobs` | Mayor |

**A-8, A-12 y A-13 ya no son de este RFC.** Verificaban el runbook, el `crontab` y la rotación,
que construyen RFC-0010 y RFC-0020. Se conservan sus números por la misma razón que los huecos de
§10.
