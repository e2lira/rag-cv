# RFC-0021 — Arranque validado de la aplicación

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aprobado |
| **Depende de** | RFC-0006, RFC-0011 |
| **Supersede** | RFC-0005 CA-13 y A-11 (*lifespan*), que pasan aquí; RFC-0011 CA-5, que deja de exigir que el arranque ocurra **sin base de datos** (§3.2) |
| **ADRs** | — |
| **Fecha** | 2026-08-23 |

---

## 1. Contexto y problema

RFC-0006 §7 entrega cinco comprobaciones de arranque como funciones que abortan con excepción, y
las deja probadas. **Nadie las llama.** Un `grep` de los cinco nombres sobre `app/` devuelve
únicamente el módulo que las define; el resto de los aciertos son tests.

La consecuencia es exactamente la que RFC-0006 §7 anticipó por escrito: *una comprobación de
arranque que nadie invoca no protege ningún arranque.* Hoy la aplicación levanta contra una base
sin migrar, con la dimensión del vector equivocada o con dos modelos de *embedding* mezclados, y
no dice nada. El fallo aparece más tarde, en una consulta, con un error que no señala la causa.

Ese cableado estaba asignado a RFC-0005 (CA-13 y A-11). El problema es dónde quedó alojado:
RFC-0005 declara `Depende de: RFC-0004`, y RFC-0004 —Strands sobre Bedrock— está superseded en
cadena por RFC-0013 §3/§6 y RFC-0018 §5, ninguno implementado. RFC-0005 entero es el contrato de
`/v1/chat`, el *streaming* SSE, la autenticación y los límites de tasa: todo detrás de la capa de
agente. Una protección **Bloqueante** quedó así detrás de tres RFCs que no existen, y mientras
tanto no protege nada.

**Y hay una contradicción activa.** RFC-0011 CA-4 exige que arrancar con el CLI de `uvicorn`
produzca un error claro sobre el bucle de eventos, *«no un error de base de datos»*. Cablear las
cinco comprobaciones en el `lifespan` de `app/main.py` produce precisamente un error de base de
datos. Los dos criterios no pueden ser ciertos sobre el mismo punto de entrada, así que el
Desarrollador que intentara cumplir CA-13 tendría que elegir cuál de los dos RFCs incumplir.

> **Corrección (§3).** El párrafo anterior daba por hecho que cablear las comprobaciones
> contradice a RFC-0011 CA-4. **No es así**, y la primera versión de este RFC construyó sobre ese
> error: `assert_compatible_loop()` corre antes que cualquier conexión, así que el CLI de `uvicorn`
> sigue fallando por el bucle de eventos y no por la base. La contradicción real es con **CA-5**,
> que es otra cosa y se resuelve de otra manera. §3.1 y §3.2 lo desarrollan; se deja escrito el
> diagnóstico equivocado porque explica por qué este RFC nació con una §3 que hubo que rehacer.

## 2. Alcance

**Entra:** la aplicación real y su `lifespan`, el origen de la conexión a base de datos en
`Settings`, el orden en que se ejecutan las cinco comprobaciones —normativo, porque de él depende
que RFC-0011 CA-4 se siga cumpliendo— y el origen de cada uno de sus parámetros.

**No entra:** `/v1/chat`, el *streaming* SSE, la autenticación por API Key, los límites de tasa,
el formato de error y CORS — todo eso sigue siendo RFC-0005 y sigue dependiendo de la capa de
agente. Tampoco entra la comprobación **6** de RFC-0006 §7 (`count(cv_chunks) > 0`), que no
aborta: describe el estado que `/readyz` debe reportar, y `/readyz` con su contrato real es de
RFC-0005.

## 3. Un punto de entrada y un lanzador

> **Esta sección se reescribió entera.** La primera versión proponía separar `app/main.py` y
> `app/dev_server.py` en dos aplicaciones. Partía de una premisa falsa, y el Desarrollador la
> devolvió con la evidencia: `app/dev_server.py:17` ejecuta `uvicorn.run("app.main:app", …)`, y
> `grep -rn "FastAPI(" app/` devuelve **un solo** objeto en todo el repositorio. `dev_server` no es
> una aplicación alternativa que pudiera separarse: es un **lanzador** de la única que hay. Lo que
> tenía dos propósitos no era `app/main.py`, era mi lectura de él.

`dev_server.py` existe por una razón concreta de RFC-0011 §5.1: el CLI de `uvicorn` crea su bucle
de eventos antes de que el proceso pueda fijar la política, y `psycopg` async exige
`SelectorEventLoop` en Windows. El lanzador fija la política y **después** arranca. Eso no cambia
aquí, y sigue apuntando a `app.main:app`.

| Módulo | Qué es | Qué hace con la base |
| :--- | :--- | :--- |
| `app/core/platform.py` | Política del bucle de eventos | Nada |
| `app/dev_server.py` | **Lanzador** de DEV: fija la política y arranca `app.main:app` | Nada por sí mismo; hereda lo que haga la aplicación |
| `app/main.py` | La única aplicación: arranca validada o no arranca | Sí, en el `lifespan` |

### 3.1 Por qué RFC-0011 CA-4 se sigue cumpliendo

`assert_compatible_loop()` es la **primera** línea del `lifespan`, antes de cualquier conexión.
Arrancar con el CLI de `uvicorn` en Windows produce un `ProactorEventLoop`, y esa comprobación
aborta ahí mismo con *«Bucle de eventos incompatible»* — sin haber tocado la base. El criterio de
RFC-0011 CA-4 —error de bucle de eventos, *«no un error de base de datos»*— se cumple **al pie de
la letra**, y su verificación (`test_platform.py::test_proactor_detected`) es un test unitario que
no arranca nada.

Esa es la contradicción que §1 daba por existente y no existe: basta con que el orden se respete.
Por eso el orden deja de ser un detalle de implementación y pasa a ser normativo (§5).

### 3.2 Lo que sí caduca: RFC-0011 CA-5

CA-5 exige que `python -m app.dev_server` arranque y `/readyz` responda `200` **sin base de
datos**. Con el lanzador la política es correcta, `assert_compatible_loop()` pasa, y el `lifespan`
sigue hasta validar la base: sin base, no arranca.

Ese criterio cumplió su función y hay que dejarlo ir, no protegerlo con un esqueleto artificial.
Nació para probar que el mecanismo del bucle de eventos funcionaba cuando no había ninguna otra
cosa que arrancar; hoy ese mecanismo lo prueba CA-4 de forma aislada y sin levantar un servidor.

Y hay una razón de fondo: **RFC-0011 entero trata de dejar al desarrollador con PostgreSQL nativo
y la base `ragcv` creada** —es literalmente su §2: «creación de la base de datos con la
configuración regional correcta»—. Quien siguió RFC-0011 tiene la base. Exigir que la aplicación
arranque sin ella protege un escenario que el propio RFC-0011 no contempla, y a cambio deja pasar
el que sí importa: arrancar contra una base que existe pero está mal.

CA-5 se acota en RFC-0011: sigue verificando que el lanzador arranca en Windows, deja de exigir
que lo haga sin base de datos.

> **Por qué no se resuelve en el PR.** Es la contradicción de dos criterios aprobados. ADU-PROCESO
> obliga a resolverla en el contrato, y RFC-0014 §6.2.2 acaba de recordar por qué: lo contrario
> convierte la excepción en el mecanismo por defecto.

El `/readyz` provisional de `app/main.py` **se queda**. La primera versión de este RFC lo retiraba,
pero eso era consecuencia de separar las dos aplicaciones: sin esa separación, retirarlo no aporta
nada y deja a RFC-0011 CA-5 sin endpoint que comprobar. RFC-0005 lo redefinirá con su contrato
real, incluida la comprobación 6 de RFC-0006 §7.

## 4. Origen de la conexión

`Settings` expone hoy las dos credenciales de API y los tres campos de *embeddings*. **No expone
`DATABASE_URL`**, aunque `.env.example` y RFC-0011 §4.5 la definen desde el principio. El
`lifespan` no tiene de dónde sacar la conexión, así que este RFC la agrega:

| Campo | Alias | Obligatorio | Origen |
| :--- | :--- | :--- | :--- |
| `database_url` | `DATABASE_URL` | Sí, sin valor por defecto | RFC-0011 §4.5, RFC-0016 §7 |

Sin valor por defecto y a propósito: una URL de base de datos por defecto es una invitación a
arrancar apuntando sin querer a la base equivocada. Que falte es un fallo de arranque, igual que
faltar una credencial (RFC-0011 CA-0').

El *pool* de conexiones ya existe (`build_pool`), y hasta ahora solo lo usaban los tests. El
`lifespan` lo abre al arrancar y lo cierra al terminar.

## 5. Orden de las comprobaciones

El orden no es indiferente: una comprobación que se ejecuta antes de tiempo falla con un error
que no señala la causa real. Si la migración no corrió, `cv_chunks` no existe, y preguntar por la
dimensión de su columna produce un error de tabla inexistente en lugar de «falta migrar».

Se ejecutan en este orden, y el primero que falla aborta:

| Orden | Comprobación | Por qué va aquí |
| :--- | :--- | :--- |
| **0** | **`assert_compatible_loop()`** (RFC-0011 §5.1) | **Normativo, y va primero.** De esto depende que RFC-0011 CA-4 se siga cumpliendo: con un `ProactorEventLoop` el proceso debe abortar por el bucle de eventos, no por la base — y no puede hacerlo si ya intentó conectarse (§3.1) |
| 1 | Extensiones `vector`, `unaccent`, `pg_trgm` presentes (RFC-0006 §7) | Sin `vector` no hay tipo de columna que inspeccionar |
| 2 | `pgvector >= 0.8` | Depende de que la extensión exista |
| 3 | Versión de Alembic == `head` esperada | Sin esquema migrado, las dos siguientes no tienen tabla que mirar |
| 4 | Dimensión de `cv_chunks.embedding` == `EMBEDDING_DIM` | Ya hay tabla; compara esquema contra configuración |
| 5 | Un único `embed_model_id` y coincide con la configuración | Ya hay tabla; compara datos contra configuración |

Dos cosas que no son obvias:

**El paso 0 no es una de las cinco.** Es la comprobación de plataforma que RFC-0011 ya dejó en el
`lifespan`; se lista aquí porque su posición dejó de ser un detalle de implementación. Moverla
después de abrir el *pool* rompería RFC-0011 CA-4 sin que ninguna prueba de este RFC lo notara.

**La 3 se adelanta.** En RFC-0006 §7 aparece como la quinta de la lista, pero esa tabla enumera
las comprobaciones, no fija su orden de ejecución. Aquí sí se fija.

## 6. Origen de cada parámetro

Tres de las cinco funciones reciben el valor esperado como argumento, y RFC-0005 CA-13 nunca dijo
de dónde sale. Se fija aquí:

| Parámetro | Origen | Por qué no de otro sitio |
| :--- | :--- | :--- |
| `expected_dim` | `settings.embedding_dim` | Es la configuración que el esquema debe reflejar |
| `minimum` (pgvector) | El valor por defecto de la función (`"0.8"`) | El mínimo lo fija RFC-0006, no el entorno |
| `expected_head` | **El árbol de migraciones del propio repositorio**, resuelto en tiempo de ejecución | Una constante escrita a mano queda obsoleta en la siguiente migración y nadie la actualiza; una variable de entorno traslada al operador un dato que el código ya conoce |
| `expected_model_id` | El `model_id` del *embedder* construido con `build_embedder` | Es la única definición de ese identificador. Componerlo a mano crearía una segunda, y las dos se separarían |

Construir el *embedder* durante el arranque **no gasta dinero**: la fábrica instancia, no llama a
la API (ADR-0012). Sí aborta si `EMBEDDER` nombra una implementación diferida, que es el
comportamiento correcto — arrancar con una configuración que no se puede satisfacer no debe
esperar a la primera consulta.

## 7. Fallos y degradación

| Situación | Comportamiento |
| :--- | :--- |
| Cualquiera de las cinco falla | El proceso **no queda listo**. El error nombra la comprobación y el valor esperado contra el encontrado |
| `DATABASE_URL` ausente o vacía | Falla la validación de `Settings`, antes de intentar conectar |
| La base no acepta conexiones | Falla el arranque, con el error de conexión, no enmascarado |
| `EMBEDDER` nombra una implementación diferida | Falla el arranque con `DeferredEmbedderError` (RFC-0017 §1) |

Ninguna de estas situaciones se degrada a un arranque parcial. Un proceso que arranca sabiendo que
su base está mal es peor que uno que no arranca: responde peticiones y las responde mal.

## 8. Criterios de aceptación

| # | Criterio | Verificación |
| :--- | :--- | :--- |
| CA-1 | El `lifespan` de `app/main.py` invoca **las cinco** comprobaciones de RFC-0006 §7 | `test_startup_wiring.py`: con cada comprobación falsificada para fallar, el arranque aborta — cinco casos, uno por comprobación |
| CA-2 | Las comprobaciones se ejecutan en el orden de §5 y la primera que falla aborta sin ejecutar las siguientes | `test_startup_wiring.py`: falsificando la primera, las posteriores no se invocan |
| CA-2b | `assert_compatible_loop()` es el **paso 0**: se ejecuta antes de abrir el *pool* y antes de las cinco | `test_startup_wiring.py`: con la comprobación de bucle falsificada para fallar, no se abre ninguna conexión ni se invoca ninguna de las cinco (RFC-0011 CA-4, §3.1) |
| CA-3 | `Settings` expone `database_url` sin valor por defecto, y su ausencia impide el arranque | `test_config.py`: sin `DATABASE_URL`, `Settings()` falla nombrando la variable |
| CA-4 | `expected_head` se deriva del árbol de migraciones, no de una constante ni del entorno | Agregar una migración nueva no obliga a editar el código del arranque |
| CA-5 | `expected_model_id` proviene del `model_id` del *embedder* construido | Cambiar `OPENAI_EMBED_MODEL` cambia el valor comprobado, sin editar el arranque |
| CA-6 | El *pool* se abre en el `lifespan` y se cierra al terminar | Inspección del `lifespan` + prueba de que no quedan conexiones abiertas |
| CA-7 | `app/dev_server.py` sigue siendo solo un lanzador: fija la política del bucle y arranca `app.main:app`, sin lógica propia ni dependencias de base de datos | Lectura del módulo — no adquiere `import` de `psycopg`, `Settings` ni `startup_checks` |
| CA-8 | El `/readyz` provisional de `app/main.py` sigue respondiendo `200` una vez que el arranque validó | `test_main.py`, contra una base válida |

## 9. Riesgos

| Riesgo | Mitigación |
| :--- | :--- |
| El arranque validado hace lento o frágil el desarrollo local | RFC-0011 ya deja al desarrollador con la base creada y el *bootstrap* es idempotente; quien solo quiere probar el mecanismo del bucle de eventos tiene `test_platform.py`, que no levanta ningún servidor |
| Alguien mueve `assert_compatible_loop()` después del *pool* en un refactor y nadie lo nota | CA-2b lo prueba explícitamente: es la única defensa de RFC-0011 CA-4 dentro de este RFC (§3.1) |
| Falsear las cinco comprobaciones en el test acopla el test a la implementación | Se falsean las funciones, no sus consultas: el test comprueba el cableado, no vuelve a probar lo que RFC-0006 ya prueba |
| Construir el *embedder* en el arranque introduce una llamada de red sin querer | ADR-0012 y RFC-0017 A-17: ninguna prueba automática llama a la API real; la fábrica solo instancia |

## Contrato de auditoría (gate ADU)

| # | Comprobación | Cómo se verifica | Severidad |
| :--- | :--- | :--- | :--- |
| A-1 | Las cinco comprobaciones están **invocadas** en el `lifespan`, no solo importadas. Una comprobación que existe y nadie llama no protege ningún arranque | CA-1 + lectura del `lifespan` | **Bloqueante** |
| A-2 | El orden de §5 se respeta y el aborto es inmediato | CA-2 | Mayor |
| A-2b | `assert_compatible_loop()` precede a la apertura del *pool* y a las cinco comprobaciones. Si no, arrancar con el CLI de `uvicorn` en Windows falla por la base y no por el bucle, y **RFC-0011 CA-4 deja de cumplirse** | CA-2b + lectura del `lifespan` | **Bloqueante** |
| A-3 | `database_url` es obligatorio y sin valor por defecto | CA-3 + lectura de `Settings` | **Bloqueante** |
| A-4 | `expected_head` no es una constante escrita a mano ni una variable de entorno | CA-4 + lectura del código | Mayor |
| A-5 | `expected_model_id` no se compone a mano en el arranque | CA-5 + lectura del código | Mayor |
| A-6 | `app/dev_server.py` sigue siendo un lanzador sin lógica propia, y **no** se lo convirtió en una segunda aplicación para esquivar el arranque validado | CA-7 + lectura del módulo (§3) | Mayor |
| A-7 | Ninguna prueba de este RFC llama a la API de *embeddings* real | `grep` sobre los tests (ADR-0012, RFC-0014 P-11) | **Bloqueante** |
| A-8 | El *pool* se cierra: el `lifespan` tiene la mitad de después del `yield` | Lectura del `lifespan` | Mayor |
