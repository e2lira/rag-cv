# RFC-0016 — Alcance de la PoC y entrega en QA (VPS Ubuntu)

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aprobado |
| **Depende de** | RFC-0007, RFC-0008, RFC-0015 |
| **Supersede** | RFC-0007 §6, §7, §9, §10 (para el alcance de la PoC); RFC-0015 §8 y la fila QA de §9; RFC-0001 §topología de despliegue; **RFC-0002 §3, solo en «versionado en Git»** (§3.3); **RFC-0007 §5.3 y RFC-0015 §7, solo en las rutas de despliegue** (§8.1). La topología y el despliegue de QA los redefine **RFC-0020**. *(RFC-0007 §5.2 lo deroga RFC-0018, no este RFC)* |
| **ADRs** | ADR-0006 |
| **Fecha** | 2026-08-22 |

---

## 1. Contexto y problema

El corpus documental describe un sistema de tres entornos cuyo destino final es AWS. ADR-0006
redujo el alcance: **la PoC se entrega en QA —un VPS Ubuntu— y AWS queda diferido.**

El problema que resuelve este RFC no es técnico, es de **lectura**. Quince RFCs aprobados
mencionan App Runner, RDS, Terraform, Secrets Manager y CloudWatch. Ninguno se edita: la
convención del proyecto (`docs/README.md` §5) es que un RFC aprobado se supersede, no se toca. Sin
un documento que declare qué sigue vigente y qué no, cualquiera que abra el repositorio no puede
distinguir **diseño diferido** de **diseño obsoleto**, y esa ambigüedad es peor que no haber
reducido el alcance.

Este RFC es ese documento: la capa que se lee **junto a** los demás para saber qué se ejecuta hoy.

> **Regla de lectura.** Un RFC marcado `Diferido` aquí **no está obsoleto ni derogado**: es
> diseño aprobado cuya ejecución se pospone. El día que se cierre ADR-0006, vuelve a ser
> normativo sin haber sido reescrito.

## 2. Alcance

**Entra:** la clasificación de todo el corpus documental frente a la PoC, la topología de
ejecución, el dimensionado del VPS, la re-lectura de los requisitos no funcionales, la
configuración consolidada y el procedimiento de despliegue y de promoción futura.

**No entra:** el modelo de embeddings (RFC-0017), el proveedor de generación (RFC-0018), la
topología de QA en sí —que RFC-0007 §5 ya especifica y este RFC no repite—, ni el diseño de PROD,
que permanece intacto en RFC-0007 §6.

## 3. Clasificación del corpus documental

Tres estados, y solo tres:

- **Vigente** — se ejecuta tal como está escrito.
- **Vigente con delta** — se ejecuta leído junto al RFC que se indica, que modifica una parte
  acotada. El original no se edita.
- **Diferido** — diseño aprobado que no se ejecuta en la PoC. No se edita, no se marca obsoleto.

### 3.1 RFCs

| RFC | Estado en la PoC | Delta / motivo |
| :--- | :--- | :--- |
| RFC-0001 Arquitectura general | Vigente con delta | La topología de despliegue y las filas de generación y embeddings se leen junto a este RFC, RFC-0017 y RFC-0018 |
| RFC-0002 Ingesta y chunking | Vigente con delta | El troceado y la normalización no cambian; la **fuente** del corpus y su disparador sí (§3.3, RFC-0019) |
| RFC-0003 Retrieval híbrido (HNSW + FTS + RRF) | **Vigente** | La degradación a rama léxica de §6 pasa a cubrir la caída del embedder local en vez de la de Bedrock |
| RFC-0004 Capa de agente Strands | Vigente con delta | La construcción del modelo ya la delegaba en RFC-0013; ahora se lee junto a RFC-0018 |
| RFC-0005 API REST y autenticación | **Vigente** | Sin cambios |
| RFC-0006 Modelo de datos y migraciones | Vigente con delta | `VECTOR(1024)` → `VECTOR(1536)` y recreación del HNSW (RFC-0017 §4). **Ojo:** RFC-0012 A-6 prohibía `1536` por corresponder a Titan G1; bajo RFC-0017 §4 es el valor correcto |
| RFC-0007 Entornos e infraestructura | Parcial | §3 y §4 **vigentes**. §5.1 y §5.3 (topología y despliegue de QA con contenedores) los **sustituye RFC-0020**; §5.2 (credenciales AWS) lo **deroga** RFC-0018. §6 (PROD), §7 (IAM), §9 (IaC) y §10 (costos AWS) **diferidos** |
| RFC-0008 CI/CD y release | Vigente con delta | El pipeline construye, prueba y despliega **hasta QA**. El paso de promoción a PROD por digest queda diferido; el job de deriva de Terraform no aplica |
| RFC-0009 Evaluación y guardrails | **Vigente** | Es el gate que decide la variante de embedder de ADR-0007. Sus umbrales no se relajan |
| RFC-0010 Observabilidad, costos y runbook | Vigente con delta | Logs JSON + rotación en el VPS **vigentes**. CloudWatch, las diez alarmas de §6 y el presupuesto de PROD, **diferidos**. El runbook mantiene §9.6c (reindexación), que este cambio ejercita |
| RFC-0011 Entorno DEV Windows nativo | Vigente con delta | Deja de necesitar `aws sso login` y salida a internet para indexar: el embedder es local (RFC-0017 §6) |
| RFC-0012 Capa de embeddings enchufable | Vigente con delta | La **interfaz, el contrato y la suite de pruebas siguen intactos**. Cambia la implementación por defecto: RFC-0017 |
| RFC-0013 Capa de proveedores LLM | Vigente con delta | La **fábrica y la parametrización siguen intactas**. Cambia el proveedor designado: RFC-0018 |
| RFC-0014 Disciplina TDD | **Vigente** | Sin cambios. Aplica a todo lo que se implemente bajo este alcance |
| RFC-0015 Empaquetado Docker y despliegue | **Diferido** | El VPS no tiene contenedores (ADR-0010). El `Dockerfile`, el `.dockerignore` y los ficheros de composición siguen siendo el diseño de empaquetado válido para el PROD diferido; en la PoC no se ejercitan. Lo sustituye **RFC-0020** |

**Los RFCs de AWS no se han tocado.** RFC-0007 §6, §7, §9 y §10 y RFC-0015 §8 conservan su
redacción original, palabra por palabra.

### 3.2 ADRs

| ADR | Estado en la PoC |
| :--- | :--- |
| ADR-0001 App Runner como cómputo de PROD | **Diferido** — sigue siendo la decisión de PROD; PROD sale del alcance |
| ADR-0002 pgvector propio en vez de Bedrock Knowledge Bases | **Vigente** — y ahora más: es lo que permite que el retrieval no dependa de AWS |
| ADR-0003 Strands Agents sobre boto3 directo | **Vigente** |
| ADR-0004 Titan V2 por defecto | **Sustituido en la PoC** por ADR-0007; sigue vigente para el camino AWS diferido |
| ADR-0005 Proveedor de generación por parametrización | **Vigente** — su designación inicial la modifica ADR-0008 |
| ADR-0010 Despliegue nativo sin contenedores | **Vigente** — es lo que difiere ADR-0001 y RFC-0015 en la práctica |

### 3.3 Fuente del corpus — la consecuencia menos evidente

Sin AWS no hay bucket. `README.md` describe **S3 como fuente autoritativa del CV** con eventos de
EventBridge, worker dedicado, DLQ y job de reconciliación, y el DDL vigente lo materializa:

```sql
-- infra/sql/001_initialize_rag_cv.sql
object_key      text NOT NULL,
s3_version_id   text NOT NULL,
s3_etag         text NOT NULL,
CONSTRAINT source_documents_object_version_key UNIQUE (object_key, s3_version_id),
```

`s3_version_id` es `NOT NULL` y participa en dos claves únicas y en claves foráneas compuestas
hacia `ingestion_jobs`. **Es la dependencia de AWS más profunda del proyecto**, porque no está en
la configuración: está en el esquema.

**Decisión para la PoC.** La fuente del corpus es un **fichero que vive en el VPS**
(`CORPUS_PATH`, RFC-0001), fuera de la imagen y fuera del repositorio, de modo que actualizar el
CV no exija un despliegue. Esto **supersede la única frase de RFC-0002 §3 que dice que el corpus
va «versionado en Git»**; el resto de esa sección —front-matter, jerarquía de encabezados, rangos
de fechas, límite de 400 palabras por unidad y prohibición de datos sensibles— sigue **vigente y
es normativa**: el cargador rechaza la ingesta si se incumple.

Que no vaya en Git no es solo consecuencia de dónde vive: **el repositorio es público y un CV
contiene datos personales.** La regla 5 de RFC-0002 §3 ya prohíbe teléfono, correo personal y
documentos de identidad dentro del corpus; no versionarlo cierra el resto del riesgo. Los eventos de S3, el worker y el job de reconciliación quedan
**diferidos** junto con el resto de AWS, y su función —detectar que el CV cambió— la asume un
**sondeo programado** cuyo contrato es RFC-0019.

**Las columnas del ledger no se eliminan: se generaliza su semántica.** Pasan de significar
"objeto de S3 y su `VersionId`" a significar "identidad de la fuente y su token de versión
opaco", que es exactamente lo que esas columnas son en S3:

| Columna | Semántica en el camino AWS | Semántica en la PoC |
| :--- | :--- | :--- |
| `object_key` | Clave del objeto en S3 | Ruta absoluta del corpus en el VPS |
| `s3_version_id` | `VersionId`: token opaco que S3 asigna en cada `PUT` | **ULID generado en el instante de la detección** |
| `s3_etag` | ETag: marcador opaco de cambio | Huella barata del fichero: `<mtime_ns>-<size>` |
| `content_sha256` | Hash del contenido | Idéntico: **la prueba del cambio real** |
| `source_metadata` | — | `inode`, `mtime_ns`, `size` y versión del detector |

El encaje no es una analogía forzada: el comentario del propio DDL dice del ETag que es un
*"opaque S3 change marker retained for traceability; it must not be used as a content hash"*.
Una huella `mtime+size` es precisamente eso — un marcador de cambio barato que **no** es un hash
de contenido — y es lo que permite que el sondeo descarte el caso habitual con un `stat`, sin
leer el fichero.

Por qué generalizar y no borrar: el ledger es lo que da idempotencia y trazabilidad —"qué versión
del CV produjo este índice"—, y esa propiedad **no depende de S3**. Borrar las columnas obligaría
a una migración destructiva ahora y a reconstruirlas al volver a AWS. Mantenerlas conserva el
camino de promoción de ADR-0006 intacto.

**Por qué el token de versión no puede ser el `content_sha256`**, que es lo primero que uno
piensa. El DDL retiró deliberadamente la unicidad de `(object_key, content_sha256)`:

```sql
-- Earlier bootstrap drafts made (object_key, content_sha256) unique. Retire that
-- constraint without deleting ledger history: S3 can create a new VersionId whose
-- bytes are unchanged, and that version must remain auditable.
```

Si el token fuera el hash del contenido, `UNIQUE (object_key, s3_version_id)` reimpondría esa
restricción por la puerta de atrás. Y no es un caso teórico: **revertir el CV a una versión
anterior** produce un `content_sha256` que ya existe en el ledger, y la inserción fallaría por
violación de unicidad en lugar de registrarse como la versión nueva que es.

**Y tampoco es el SHA de commit de git**, que es lo que este RFC declaraba en su primera
redacción. Esa decisión asumía que el corpus viajaba con el repositorio o con la imagen. **No es
así**: el fichero vive en el VPS y se edita ahí, sin pasar por git. Un commit no identifica una
revisión que git nunca vio.

El ULID cumple lo que se necesita y no depende de nada externo: opaco, único por detección,
ordenable por tiempo y **generado del lado del servidor**, igual que un `VersionId`. Una revisión
con bytes idénticos a otra anterior entra como fila nueva y auditable, y el trabajo asociado se
resuelve por `content_sha256` — que es el comportamiento que `README.md` ya describía.

**Los nombres de columna no se renombran en la PoC.** Un renombrado toca dos claves únicas y dos
claves foráneas compuestas sobre un esquema ya desplegado, a cambio de nada funcional. Se hace, si
se hace, al cerrar ADR-0006.

## 4. Topología de ejecución de la PoC

**El VPS no tiene contenedores y el despliegue es por SSH plano (ADR-0010).** La topología de
procesos, el aprovisionamiento, la supervisión con `systemd` de usuario y el procedimiento de
despliegue con identidad de release son el contrato de **RFC-0020**, y no se repiten aquí.

Lo que interesa a este RFC es qué cambia respecto al diseño anterior:

| Aspecto | RFC-0007 §5 (con contenedores) | Alcance vigente (RFC-0020) |
| :--- | :--- | :--- |
| Ejecución | `docker compose`: `caddy`, `api`, `db` | Procesos nativos; `caddy` y `postgresql` como servicios del sistema, la API como unidad de usuario |
| Base de datos | `pgvector/pgvector:pg16` en contenedor | PostgreSQL 16 + pgvector del sistema, `listen_addresses = 'localhost'` |
| Embeddings | Bedrock con usuario IAM | API de OpenAI, `text-embedding-3-small` (RFC-0017) |
| Generación | Bedrock con usuario IAM | API de Anthropic (RFC-0018) |
| Corpus | Objeto en S3 con eventos | Fichero en el VPS, vigilado por sondeo (§3.3, RFC-0019) |
| Artefacto | Imagen de contenedor por *digest* | **Commit de git**, expuesto en `/readyz` (RFC-0020 §6) |

De las tres dependencias externas del diseño original —Bedrock para generación, Bedrock para
embeddings y S3 para el corpus— **no queda ninguna de AWS**. Quedan dos llamadas salientes, a dos
proveedores **distintos**: Anthropic para generar y OpenAI para embeber. Que sean distintos importa:
una caída no se lleva las dos cosas, que es justo lo que fallaba cuando Bedrock era ambas.

## 5. Dimensionamiento del VPS

**VPS contratado: 2 núcleos y 8 GB de RAM.**

Este apartado existía porque autoalojar el embedder convertía el tamaño del host en un requisito de
arquitectura. **ADR-0007 lo retiró**: el VPS no tiene capacidad de cómputo para sostener inferencia
local, y los embeddings pasan a resolverse por API. Sin modelo en memoria, el dimensionado vuelve a
ser holgado:

| Componente | Memoria estimada |
| :--- | :--- |
| Sistema operativo (Ubuntu 24.04, sin escritorio) | ~400 MB |
| Caddy | ~30 MB |
| API (`uvicorn`, 2 *workers*) | ~350 MB |
| PostgreSQL 16 + pgvector | ~400 MB |

Poco más de 1 GB en reposo sobre 8 GB disponibles. **La memoria deja de ser un tema**, y con ella
el criterio de aceptación que la vigilaba pasa a ser una comprobación de rutina, no un riesgo.

**Los 2 núcleos también dejan de ser el cuello.** Con inferencia local, embeber una consulta habría
sido cómputo compitiendo con la generación de respuestas; por API vuelve a ser una **espera de
red**, que es lo que el presupuesto de latencia de RFC-0001 §8 asumía desde el principio. Lo que
queda por medir es la latencia de esa espera bajo tráfico concurrente (CA-4), no la contención de
CPU.

Conviene dejar registrado el porqué, para que nadie reintroduzca inferencia local sin volver a
pensarlo: **este host no da para servir un modelo**, y esa restricción es la que decidió ADR-0007.

## 6. Re-lectura de los requisitos no funcionales

Reducir el alcance obliga a declarar qué se sigue midiendo y qué **deja de verificarse**. Dar por
cumplido un umbral que ya no se mide sería el peor resultado de este RFC.

| RNF | Estado en la PoC | Motivo |
| :--- | :--- | :--- |
| RNF-1, RNF-2, RNF-3 (latencias) | **Se miden**, en QA | La evaluación de RFC-0009 las registra en su propia ejecución |
| RNF-4 (disponibilidad ≥ 99.5 %) | **No verificado** | Un host único no tiene alta disponibilidad. Se declara no verificado, no cumplido |
| RNF-5 (costo por conversación ≤ USD 0.05) | **Se mide** | De `usage.cost_usd`; ahora es el único freno de coste (ADR-0008) |
| RNF-6 (costo de PROD ≤ USD 60/mes) | **No aplica** | No hay PROD. El costo de la PoC es el del VPS, fijo |
| RNF-7 (la BD nunca se expone a internet) | **Se cumple** | `listen_addresses = 'localhost'` y `ufw` sin el 5432 (RFC-0020 §7) |
| RNF-8 (secretos fuera del repositorio) | **Se cumple** | `ANTHROPIC_API_KEY` en `$RAG_CV_HOME/.env` con permisos `600` (§8.1) |
| RNF-9 (límite de tasa por API Key) | **Se cumple** | Sin cambios (RFC-0005) |
| RNF-10 (imagen construida una vez, promovida por digest) | **No verificado, sustituido** | Sin contenedores no hay imagen ni digest (ADR-0010). Se conserva la propiedad que protegía —que lo que corre en QA sea lo que el CI validó— mediante el SHA de commit expuesto en `/readyz` (RFC-0020 §6). Es un sustituto más débil: garantiza qué código corre, no con qué dependencias del sistema |
| RNF-11 (independencia del sistema operativo) | **Se cumple** | Sin cambios: el CI en Linux sigue siendo la autoridad |
| RNF-12 (vectores comparables entre entornos) | **Se cumple**, y mejor | DEV y QA corren el mismo modelo fijado por *digest*, sin dos caminos de servicio (RFC-0017 §6) |
| RNF-13 (cambiar de modelo sin tocar código) | **Se demuestra** | Este cambio de alcance es su verificación: se cambian embedder y proveedor por configuración |

## 7. Configuración consolidada de la PoC

Las variables las definen RFC-0012, RFC-0013, RFC-0007 y RFC-0019; aquí solo se fija **el valor vigente**
para no obligar a reconstruir la configuración leyendo cinco documentos.

| Variable | Valor en la PoC | Origen |
| :--- | :--- | :--- |
| `APP_ENV` | `qa` | RFC-0007 |
| `EMBEDDER` | `openai` | RFC-0017 |
| `EMBEDDING_DIM` | `1536` | RFC-0017 |
| `OPENAI_EMBED_MODEL` | `text-embedding-3-small` | RFC-0017 §5 |
| `OPENAI_API_KEY` | secreto, `.env` con permisos `600` | RFC-0017 §6 |
| `PROVEEDOR` | `anthropic` | RFC-0018 |
| `ANTHROPIC_MODEL_ID` | `claude-haiku-4-5` | RFC-0018 |
| `ANTHROPIC_API_KEY` | secreto, `.env` con permisos `600` | RFC-0018 |
| `CORPUS_PATH` | ruta absoluta del CV en el VPS | RFC-0016 §3.3, RFC-0019 |
| `WATCHER_*` | cadencia, estabilidad, *lease*, intentos y latido | RFC-0019 §8 |
| `AWS_REGION`, `BEDROCK_MODEL_ID`, `TITAN_MODEL_ID` | **ausentes** | Sin uso en la PoC |

Que las variables de AWS estén **ausentes y no vacías** es deliberado: `Settings` valida por rama
(RFC-0012 §5, RFC-0013 §5), y una variable presente con valor vacío es la forma habitual de que un
despliegue arranque a medias en lugar de fallar de inmediato.

## 8. Despliegue y promoción futura

### 8.1 Rutas, cuentas y privilegios en el VPS

RFC-0007 §5.3 y RFC-0015 §7 sitúan el despliegue en `/opt/rag-cv`, y RFC-0007 §5.2 lo asigna a un
usuario de servicio sin shell. **Hay acceso de administrador en el VPS, pero la operación diaria
no lo usa**: se entra con la cuenta `qrimapp-reto`, y el despliegue vive bajo su directorio
personal.

Esa distinción es la decisión de esta sección, y no es cosmética: **separa el privilegio por
momento, no por persona.**

| Rol | Cuándo | Con qué cuenta | Qué hace |
| :--- | :--- | :--- | :--- |
| **Aprovisionamiento** | Una vez por VPS | `root` o `sudo` | Instala PostgreSQL, pgvector, Caddy y Python; abre el cortafuegos; crea el árbol y su propiedad; habilita `linger` (RFC-0020 §4) |
| **Operación** | Cada release, cada ciclo del sondeo | `qrimapp-reto` | Despliega, migra, indexa, reinicia unidades de usuario, lee bitácoras. **Nunca necesita `sudo`** |

Que la operación no requiera `sudo` no es comodidad: es lo que permite que el `crontab` del
sondeo y el despliegue por SSH ocurran sin credenciales de administrador en ninguna
automatización. Un pipeline que necesita `sudo` acaba teniendo un `NOPASSWD` instalado y olvidado.

**Y sin contenedores esa separación vale de verdad.** El diseño anterior obligaba a meter la
cuenta en el grupo `docker`, y pertenecer a ese grupo **equivale a `root`**: quien habla con el
demonio monta la raíz en un contenedor y sale con privilegios totales. Operar como `qrimapp-reto`
habría acotado el error accidental, no el privilegio alcanzable. Al desaparecer el demonio
(ADR-0010), la cuenta de operación tiene de verdad el privilegio que aparenta.

Toda ruta se deriva de una única raíz, para que un cambio de hospedaje sea un cambio de una línea
y no una búsqueda por cinco documentos:

```sh
RAG_CV_HOME=/home/qrimapp-reto/rag-cv
```

| Qué | Ruta | Propiedad y permisos | Sustituye a |
| :--- | :--- | :--- | :--- |
| Releases | `$RAG_CV_HOME/releases/<sha>/` | `qrimapp-reto`, `755` | La imagen por *digest* (RFC-0015) |
| Release activa | `$RAG_CV_HOME/current` (enlace simbólico) | `qrimapp-reto` | — |
| Secretos | `$RAG_CV_HOME/.env` | `qrimapp-reto`, **`600`** | `/opt/rag-cv/.env` (RFC-0007 §5.2, RFC-0015 §7) |
| Corpus (`CORPUS_PATH`) | `$RAG_CV_HOME/corpus/cv.md` | `qrimapp-reto`, `644` | — |
| Bitácora del sondeo | `$RAG_CV_HOME/logs/watcher.log` | `qrimapp-reto`, `640` | `/var/log/rag-cv/` (RFC-0019 §7) |
| Programación del sondeo | `crontab` de `qrimapp-reto` | — | `/etc/cron.d/` (RFC-0019 §7) |
| Unidades de servicio | `~/.config/systemd/user/` | `qrimapp-reto` | Servicios del compose (RFC-0015 §7) |

**Puertos 80 y 443.** Los abre `caddy` como servicio del sistema, instalado en el
aprovisionamiento (RFC-0020 §4). No hacen falta capacidades ni ajustar
`net.ipv4.ip_unprivileged_port_start` para la cuenta de operación, porque no es ella quien los
abre.

**Lo que se renuncia, y conviene decirlo entero:**

| Renuncia | Consecuencia real |
| :--- | :--- |
| Usuario de servicio sin shell | Los procesos corren como una cuenta con inicio de sesión. Quien entre por SSH como `qrimapp-reto` **lee el `.env` y controla el despliegue**. Los `600` protegen frente a otras cuentas del host, no frente a la propia |
| `/etc/logrotate.d` | La rotación se hace en espacio de usuario, con estado propio (RFC-0019 §7). Es una pieza más que puede quedar sin instalar, y por eso tiene criterio de aceptación |
| Aislamiento entre servicios | Sin contenedor no hay frontera implícita. Se sustituye con `MemoryMax` y `CPUWeight` en las unidades (RFC-0020 §5) |

Los permisos `600` sobre el `.env` **siguen siendo exigibles** y son lo que sostiene RNF-8.

### 8.2 Aprovisionamiento y despliegue

El procedimiento completo —paquetes, cortafuegos, `enable-linger`, unidades de usuario,
sincronización por `rsync`, migración y conmutación atómica de la release— es **RFC-0020 §4 y §6**.
Aquí solo quedan los dos pasos propios del alcance de la PoC, ambos de **aprovisionamiento**:

```bash
# sondeo del corpus: sin esto NO falla nada, y ahi esta el problema
crontab cron/rag-cv-watcher                        # RFC-0019 §7
```

**Este paso es el peligroso, y conviene entender por qué.** Casi todo lo que se puede olvidar en
este despliegue falla ruidosamente: una clave ausente impide el arranque, un embedder que no
responde pone `/readyz` en rojo, una migración rota no conmuta la release. **El `crontab` no.** Si
se omite, el servicio arranca en verde y sirve consultas correctamente; solo deja de enterarse de
los cambios del CV. Es el modo de fallo silencioso de ADR-0009, y la razón por la que RFC-0019 §7
exige un latido con alerta por ausencia en vez de confiar en que el paso se recuerde.

**Promoción futura a PROD.** Cerrar ADR-0006 exigirá construir y validar la imagen de RFC-0015,
que en la PoC nunca se habrá ejercitado (ADR-0010 lo declara como deuda). El diseño de PROD de
RFC-0007 §6 sigue intacto y disponible; lo que habrá que decidir entonces es si los modelos
vuelven a Bedrock —ADR-0004 y ADR-0005 recuperan vigencia— o se mantienen los de la PoC. Esa
decisión es del Arquitecto y no se anticipa aquí.

## 9. Fallos y degradación

| Fallo | Detección | Comportamiento |
| :--- | :--- | :--- |
| El proveedor de embeddings no responde | `/readyz`, comprobación 4c de RFC-0012 §7 | Consulta: degrada a **solo rama léxica** con `degraded=true` (RFC-0003 §6). Indexación: `rollback` completo |
| Modelo no descargado en el VPS | Primer arranque | `/readyz` en rojo con el nombre del modelo esperado. No arranca a medias |
| OOM del host | El kernel mata el proceso mayor | Con 8 GB deja de ser el riesgo principal (§5). Se acota además con `MemoryMax` por unidad (RFC-0020 §5), que degrada el servicio culpable en vez del host |
| API de Anthropic caída o con error de cuota | Cliente del proveedor | RFC-0013 §7: reintentos y fallo explícito. El *fallback* sigue apagado por defecto (ADR-0005) |
| El sondeo del corpus deja de ejecutarse | Latido caducado (RFC-0019 §7) | Alerta. El índice queda desactualizado **sin dar error**: es el modo de fallo característico de ADR-0009 |
| Cae la API de embeddings | `/readyz` y cliente | Consulta: degrada a rama léxica. **No afecta a la generación** |
| El VPS cae | Sonda externa | **No hay servicio.** Punto único de fallo aceptado en ADR-0006 |

La diferencia importante frente al diseño anterior: la caída del embedder ya **no** coincide con
la caída del generador. Antes ambos eran Bedrock y una incidencia regional se llevaba los dos;
ahora son dos proveedores independientes, y la degradación a rama léxica cubre el primero sin tocar
el segundo.

## 10. Criterios de aceptación

| # | Criterio | Verificación |
| :--- | :--- | :--- |
| CA-1 | Solo `caddy` escucha en interfaces públicas; API y PostgreSQL solo en el bucle local | `ss -ltnp` en el VPS (RFC-0020 CA-4) |
| CA-2 | La aplicación arranca y sirve `/readyz` en verde **sin ninguna credencial de AWS presente** en el entorno | Despliegue con `env` sin variables `AWS_*` |
| CA-3 | No queda ninguna referencia a `bedrock`, `titan` ni `AWS_REGION` en la configuración efectiva de la PoC | `systemctl --user show-environment` + lectura del `.env` |
| CA-4 | La latencia p95 de recuperación cabe en RNF-3 con tráfico concurrente y durante una indexación completa | Latencia medida durante la indexación con tráfico simultáneo |
| CA-5 | La suite de evaluación de RFC-0009 se ejecuta completa contra QA y publica sus métricas | `invoke evals --suite full` contra el despliegue de QA |
| CA-6 | El pipeline de RFC-0008 llega hasta QA por SSH y no intenta ningún paso de AWS ni de registro de imágenes | Ejecución del workflow en verde |
| CA-7 | RNF-4 y RNF-6 aparecen declarados **no verificados** en el informe de la PoC, no como cumplidos | Lectura del informe |
| CA-8 | Los RFCs y ADRs marcados `Diferido` conservan su contenido sin modificaciones | `git log --follow` sobre RFC-0007 y RFC-0015 |
| CA-9 | Dos despliegues consecutivos sin cambios de corpus no violan unicidad y no regeneran embeddings | Ejecutar `§8` dos veces seguidas sin tocar el corpus |
| CA-11 | El sondeo del corpus está instalado y su latido se actualiza tras el despliegue | RFC-0019 CA-10 sobre el VPS |
| CA-12 | Caddy sirve en 443 y la cuenta de operación no pertenece a ningún grupo equivalente a `root` | `id -nG qrimapp-reto` + `curl -fsS https://qa.<dominio>/readyz` |
| CA-13 | Ninguna ruta de despliegue queda fuera de `$RAG_CV_HOME`, todo pertenece a `qrimapp-reto` y el `.env` conserva permisos `600` | `ls -l` sobre el árbol de despliegue |
| CA-14 | Ninguna operación de despliegue, indexación o sondeo requiere `sudo` | Ejecutar el ciclo completo con la cuenta de operación |
| CA-10 | El token de versión persistido es un ULID por detección, **no** el `content_sha256` ni un SHA de commit | Consulta a `source_documents` tras dos ingestas |

## 11. Riesgos

| Riesgo | Mitigación |
| :--- | :--- |
| Alguien lee un RFC diferido y lo implementa creyéndolo vigente | §3 es la fuente única de estado; `docs/README.md` lo refleja en su índice |
| Se declara RNF-4 cumplido porque "en QA no se cayó" | CA-7 lo convierte en comprobación auditable |
| Alguien reintroduce inferencia local sin recordar que este host no da para servir un modelo | §5 lo deja registrado con su motivo; revertirlo exige reabrir ADR-0007 |
| `Diferido` se lee como `Obsoleto` y alguien borra el diseño de AWS | Regla de lectura explícita en §1 y CA-8 |
| La reducción de alcance se usa para relajar los umbrales de RFC-0009 | RFC-0009 se declara **Vigente** sin delta: los umbrales no se tocan |
| Dos secretos de larga vida en el VPS en vez de uno | `600` en el `.env`, `SecretStr`, `gitleaks` en CI y exclusión en el `rsync` (RFC-0020 §6) |
| Una sesión SSH comprometida con la cuenta de operación da acceso a los secretos y al despliegue | Declarado en §8.1. Se acota con acceso por clave sin contraseña (RFC-0007 §5.1) y `600` en el `.env` |
| Reintroducir contenedores metería la cuenta en el grupo `docker`, que equivale a `root` | §8.1 lo declara; si se revierte ADR-0010 hay que revisar esta decisión, no heredarla |
| Sin imagen, «desplegamos el commit X» deja de ser comprobable | RFC-0020 CA-5: el SHA se expone en `/readyz` |
| Deriva de dependencias del sistema al no viajar con un artefacto | Deuda declarada en ADR-0010; RFC-0020 CA-9 la ejercita sobre un host limpio |

## Contrato de auditoría (gate ADU)

| # | Comprobación | Cómo se verifica | Severidad si falla |
| :--- | :--- | :--- | :--- |
| A-1 | Ningún RFC ni ADR marcado `Diferido` ha sido editado | `git diff` contra el commit previo al cambio de alcance | Bloqueante |
| A-2 | La aplicación arranca y responde sin ninguna variable `AWS_*` en el entorno | CA-2, CA-3 | Bloqueante |
| A-3 | Ni la base de datos ni la API escuchan fuera del bucle local | CA-1 | Bloqueante |
| A-4 | La latencia de recuperación está medida en el host real bajo tráfico concurrente | §5 + CA-4 | Mayor |
| A-4b | El `.env` tiene permisos `600` y ninguna ruta de despliegue escapa de `$RAG_CV_HOME` | CA-13 | Bloqueante |
| A-4c | La renuncia al usuario de servicio sin shell está declarada como riesgo aceptado, no omitida | §8.1 | Mayor |
| A-4d | La operación diaria no usa `root` ni `sudo` en ninguna automatización | CA-14 | Mayor |
| A-4e | La cuenta de operación no pertenece a ningún grupo equivalente a `root` | CA-12 | Mayor |
| A-5 | RNF-4 y RNF-6 figuran como **no verificados** en el informe de la PoC | CA-7 | Bloqueante |
| A-6 | Los umbrales de RFC-0009 no se han modificado | `git diff` sobre RFC-0009 | Bloqueante |
| A-7 | El índice de `docs/README.md` refleja el estado de cada RFC frente a la PoC | Lectura | Menor |
| A-8 | El token de versión del ledger no es el `content_sha256`; revertir el CV a una versión anterior inserta fila en vez de fallar | CA-10 + RFC-0019 CA-8 | Bloqueante |
| A-9 | Reindexar sin cambios de corpus es idempotente y no falla por unicidad | CA-9 | Bloqueante |
| A-10 | El paso de aprovisionamiento del modelo está en el runbook | Lectura de RFC-0010 §9 | Menor |
