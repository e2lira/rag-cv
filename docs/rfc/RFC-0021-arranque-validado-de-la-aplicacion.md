# RFC-0021 — Arranque validado de la aplicación

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aprobado |
| **Depende de** | RFC-0006, RFC-0011 |
| **Supersede** | RFC-0005 CA-13 y A-11 (*lifespan*), que pasan aquí; RFC-0011 §2 en cuanto a qué punto de entrada es el esqueleto |
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

La causa raíz de las dos cosas es la misma: **`app/main.py` se llama como la aplicación real pero
su propio docstring se declara esqueleto de RFC-0011.** Un punto de entrada con dos propósitos.

## 2. Alcance

**Entra:** la separación de los dos puntos de entrada, la aplicación real y su `lifespan`, el
origen de la conexión a base de datos en `Settings`, el orden en que se ejecutan las cinco
comprobaciones y el origen de cada uno de sus parámetros.

**No entra:** `/v1/chat`, el *streaming* SSE, la autenticación por API Key, los límites de tasa,
el formato de error y CORS — todo eso sigue siendo RFC-0005 y sigue dependiendo de la capa de
agente. Tampoco entra la comprobación **6** de RFC-0006 §7 (`count(cv_chunks) > 0`), que no
aborta: describe el estado que `/readyz` debe reportar, y `/readyz` con su contrato real es de
RFC-0005.

## 3. Los dos puntos de entrada

RFC-0011 §2 construyó un esqueleto para poder verificar que `uvicorn` arranca en Windows sin el
error de bucle de eventos. Ese esqueleto es legítimo y debe seguir existiendo **sin tocar base de
datos**: si dependiera de una base viva, dejaría de poder distinguir un fallo de bucle de eventos
de un fallo de conexión, que es justo lo que CA-4 existe para separar.

Lo que no es legítimo es que ese esqueleto ocupe el nombre de la aplicación real.

| Módulo | Qué es | Toca base de datos | Criterios que lo protegen |
| :--- | :--- | :--- | :--- |
| `app/dev_server.py` | Esqueleto de DEV: prueba que `uvicorn` arranca en Windows | **No, nunca** | RFC-0011 CA-4, CA-5 |
| `app/main.py` | La aplicación real: arranca validada o no arranca | Sí, en el `lifespan` | Este RFC |

`app/main.py` deja de ser esqueleto. Su `/readyz` provisional —el que responde `200` sin mirar
nada— se retira: quien necesite ese comportamiento tiene `app/dev_server.py`, y el `/readyz` con
contrato real es de RFC-0005.

> **Por qué no basta con anotar la excepción en un PR.** Es la contradicción de dos criterios
> aprobados, no un detalle de implementación. ADU-PROCESO obliga a resolverla en el contrato, y
> RFC-0014 §6.2.2 acaba de recordar por qué: lo contrario convierte la excepción en el mecanismo
> por defecto.

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

| Orden | Comprobación (RFC-0006 §7) | Por qué va aquí |
| :--- | :--- | :--- |
| 1 | Extensiones `vector`, `unaccent`, `pg_trgm` presentes | Sin `vector` no hay tipo de columna que inspeccionar |
| 2 | `pgvector >= 0.8` | Depende de que la extensión exista |
| 3 | Versión de Alembic == `head` esperada | Sin esquema migrado, las dos siguientes no tienen tabla que mirar |
| 4 | Dimensión de `cv_chunks.embedding` == `EMBEDDING_DIM` | Ya hay tabla; compara esquema contra configuración |
| 5 | Un único `embed_model_id` y coincide con la configuración | Ya hay tabla; compara datos contra configuración |

Nótese que **3 se adelanta**: en RFC-0006 §7 aparece como la quinta de la lista, pero esa tabla
enumera las comprobaciones, no fija su orden de ejecución. Aquí sí se fija, y la razón es la de
arriba.

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
| CA-3 | `Settings` expone `database_url` sin valor por defecto, y su ausencia impide el arranque | `test_config.py`: sin `DATABASE_URL`, `Settings()` falla nombrando la variable |
| CA-4 | `expected_head` se deriva del árbol de migraciones, no de una constante ni del entorno | Agregar una migración nueva no obliga a editar el código del arranque |
| CA-5 | `expected_model_id` proviene del `model_id` del *embedder* construido | Cambiar `OPENAI_EMBED_MODEL` cambia el valor comprobado, sin editar el arranque |
| CA-6 | El *pool* se abre en el `lifespan` y se cierra al terminar | Inspección del `lifespan` + prueba de que no quedan conexiones abiertas |
| CA-7 | `app/dev_server.py` sigue sin tocar base de datos y `/readyz` responde `200` | RFC-0011 CA-5, sin cambios |
| CA-8 | `app/main.py` ya no expone el `/readyz` provisional del esqueleto | El endpoint no existe en `app/main.py` |

## 9. Riesgos

| Riesgo | Mitigación |
| :--- | :--- |
| El arranque validado hace lento o frágil el desarrollo local | `app/dev_server.py` sigue arrancando sin base de datos: quien solo prueba el bucle de eventos no paga el costo |
| Falsear las cinco comprobaciones en el test acopla el test a la implementación | Se falsean las funciones, no sus consultas: el test comprueba el cableado, no vuelve a probar lo que RFC-0006 ya prueba |
| Construir el *embedder* en el arranque introduce una llamada de red sin querer | ADR-0012 y RFC-0017 A-17: ninguna prueba automática llama a la API real; la fábrica solo instancia |

## Contrato de auditoría (gate ADU)

| # | Comprobación | Cómo se verifica | Severidad |
| :--- | :--- | :--- | :--- |
| A-1 | Las cinco comprobaciones están **invocadas** en el `lifespan`, no solo importadas. Una comprobación que existe y nadie llama no protege ningún arranque | CA-1 + lectura del `lifespan` | **Bloqueante** |
| A-2 | El orden de §5 se respeta y el aborto es inmediato | CA-2 | Mayor |
| A-3 | `database_url` es obligatorio y sin valor por defecto | CA-3 + lectura de `Settings` | **Bloqueante** |
| A-4 | `expected_head` no es una constante escrita a mano ni una variable de entorno | CA-4 + lectura del código | Mayor |
| A-5 | `expected_model_id` no se compone a mano en el arranque | CA-5 + lectura del código | Mayor |
| A-6 | `app/dev_server.py` no adquirió ninguna dependencia de base de datos | `grep` sobre el módulo + RFC-0011 CA-5 | **Bloqueante** |
| A-7 | Ninguna prueba de este RFC llama a la API de *embeddings* real | `grep` sobre los tests (ADR-0012, RFC-0014 P-11) | **Bloqueante** |
| A-8 | El *pool* se cierra: el `lifespan` tiene la mitad de después del `yield` | Lectura del `lifespan` | Mayor |
