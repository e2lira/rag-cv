# RFC-0014 — Disciplina TDD verificable

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aprobado |
| **Depende de** | RFC-0008, RFC-0009 |
| **Aplica a** | Todo el código de `app/`, `evals/` e `ingestion` |
| **Fecha** | 2026-08-22 |

---

## 1. Contexto y problema

En ADU, el Arquitecto escribe criterios de aceptación y el Desarrollador —otro modelo— los
implementa. El riesgo estructural de ese reparto es la **ambigüedad**: un criterio en prosa
admite varias lecturas, y el Desarrollador implementará la suya. El Auditor entonces discute
interpretaciones en vez de verificar hechos.

TDD resuelve exactamente eso. Un test es un criterio de aceptación **en forma ejecutable**: no
admite dos lecturas, y su resultado es un hecho, no una opinión. Por eso en este proyecto TDD no
es una preferencia de estilo: es **el mecanismo que hace auditable el trabajo entre modelos**.

Y hay un segundo problema, específico de este sistema: **una parte del comportamiento no es
determinista**. No se puede escribir un test unitario que afirme qué palabras dirá un LLM. Este
RFC traza esa frontera con precisión, porque intentar hacer TDD del modelo produce tests frágiles
que se acaban borrando, y no hacer TDD de nada por esa excusa produce un sistema sin red.

## 2. Alcance

**Entra:** el orden normativo de trabajo, la frontera entre lo determinista y lo no
determinista, la taxonomía de pruebas, cómo se **demuestra** que los tests se escribieron
primero, prohibiciones, cobertura y prueba de mutación.

**No entra:** la suite de evaluación del agente (RFC-0009), el pipeline (RFC-0008).

## 3. El orden es normativo

Para cada criterio de aceptación de un RFC, el ciclo es:

```
1. ROJO      Escribir el test que codifica el criterio. Ejecutarlo. DEBE fallar,
             y debe fallar por la razón correcta (no por un ImportError).
2. VERDE     Escribir el código mínimo que lo hace pasar. Nada más.
3. REFACTOR  Mejorar el diseño sin tocar los tests. Siguen en verde.
```

Reglas que lo hacen operable:

- **Un ciclo por criterio de aceptación**, no uno por RFC. Un RFC con 12 criterios son 12 ciclos.
- **El test se escribe leyendo el RFC, no leyendo el código.** Si el Desarrollador necesita ver
  una implementación para saber qué afirmar, el criterio está mal escrito y se devuelve al
  Arquitecto (ADU-PROCESO §4, Definition of Ready).
- **El rojo tiene que ser un rojo real.** Un test que falla con `ModuleNotFoundError` no ha
  demostrado nada sobre el comportamiento. Se crea antes el módulo con la firma y un cuerpo que
  lance `NotImplementedError`; entonces el fallo del test dice algo.
- **El verde es mínimo.** Si al implementar surge una capacidad que ningún test exige, esa
  capacidad no entra: o se añade el criterio al RFC (vuelta al Arquitecto) o no se escribe.

### 3.1 Primera tarea de cada handoff

Es la instrucción explícita del Arquitecto al Desarrollador, y está en el prompt del rol
(`docs/adu/prompts/PROMPT-DESARROLLADOR-TDD.md`):

> **Lo primero que produces de cada RFC es la suite de tests, en rojo, con un commit propio.
> No escribes una línea de implementación antes de ese commit.**

## 4. La frontera: qué se prueba con TDD y qué no

Esta tabla es la parte más importante del RFC.

| Componente | ¿Determinista? | Cómo se verifica |
| :--- | :--- | :--- |
| Validación y troceado del corpus (RFC-0002) | Sí | **TDD estricto**. Entrada fija → fragmentos fijos |
| Cabecera de contexto y metadatos | Sí | **TDD estricto** |
| Fusión RRF, diversificación, umbral (RFC-0003) | Sí | **TDD estricto**, con rangos sintéticos y sin BD |
| SQL de búsqueda híbrida | Sí | **TDD** con base efímera y `FakeEmbedder` |
| `task_type` / prefijos y normalización (RFC-0012) | Sí | **TDD estricto** sobre el cuerpo enviado al proveedor |
| Fábrica de proveedores y validación de `Settings` (RFC-0013) | Sí | **TDD estricto** |
| API Key, roles, límite de tasa, formato de error (RFC-0005) | Sí | **TDD estricto** |
| Esquema, migraciones, idempotencia de la ingesta (RFC-0006) | Sí | **TDD** con base efímera |
| Orquestación del turno, memoria, límites de herramientas (RFC-0004) | Sí, **con un modelo falso** | **TDD** con `FakeModel` de guion fijo |
| Serialización SSE, orden de eventos | Sí | **TDD estricto** |
| **El texto que produce el LLM** | **No** | **Nunca con TDD.** Suite de evaluación (RFC-0009) con umbrales y comparación contra línea base |
| **La calidad de la recuperación semántica** | **No** exactamente | Métricas (*context recall*, *precision*) sobre el conjunto dorado, con umbral |

La clave está en la penúltima fila del bloque determinista: **el agente sí es testeable con TDD
siempre que el modelo sea un doble**. Que el agente llame a `search_cv` una vez ante una
pregunta factual, que no la llame ante un saludo, que corte a las dos llamadas, que no mezcle
historiales entre conversaciones — todo eso es lógica de orquestación propia, y se prueba con un
`FakeModel` que devuelve un guion. Lo único que queda fuera es **qué palabras** elige el modelo
real, y para eso está la evaluación.

**Regla derivada:** un test unitario **nunca** llama a un LLM ni a un embedder real. Si lo hace,
es un test de integración o una evaluación, y va a otra carpeta con otro marcador.

## 5. Taxonomía y presupuesto

| Nivel | Marcador | Qué usa | Presupuesto | Cuándo corre |
| :--- | :--- | :--- | :--- | :--- |
| Unitario | `-m unit` | `FakeEmbedder`, `FakeModel`, sin IO ni red | < 2 min total | Cada guardado, cada push |
| Integración | `-m integration` | PostgreSQL efímero, `FakeEmbedder` | < 5 min | Cada push |
| Contrato de proveedor | `-m provider` | Nomic API y LLM reales | < 3 min | Antes de promover a QA |
| Adversarial | `-m adversarial` | LLM real | < 4 min | Cada PR |
| Evaluación | `evals/` | LLM y embedder reales | < 6 min | Cada PR (suite reducida) |

Un test unitario que tarde más de 100 ms es sospechoso: casi siempre significa que está tocando
algo que debería estar doblado.

## 6. Cómo se demuestra que los tests se escribieron primero

Esta sección existe porque "hicimos TDD" no es verificable por afirmación, y el Auditor no puede
aceptar afirmaciones (ADU-PROCESO §2). Tres evidencias, en orden de fuerza:

### 6.1 Orden de commits (necesaria, no suficiente)

El PR contiene, para cada criterio, un commit de test **anterior** al de implementación:

```
test(retrieval): RRF es determinista ante empates [RFC-0003 CA-4]
feat(retrieval): desempate por chunk_id en la fusión RRF [RFC-0003 CA-4]
```

El Auditor lo verifica con `git log --reverse --oneline` sobre el rango del PR. **No se permite
aplastar los commits al fusionar** (*squash* deshabilitado en la rama, RFC-0008): el historial
del PR es la evidencia, y aplastarlo la destruye.

Es necesaria pero no suficiente: alguien puede escribir el test después y commitearlo antes.

#### 6.1.1 Cuál de las dos formas del ciclo aplica (normativo)

El proceso describe el ciclo TDD de dos formas, y hasta ahora no decía cuándo usar cada una:

| Forma | Cómo se ve en el historial | Cuándo es **obligatoria** |
| :--- | :--- | :--- |
| **Por criterio** | `test(...) CA-1` → `feat(...) CA-1` → `test(...) CA-2` → `feat(...) CA-2` … | Cuando cada criterio tiene una implementación **separable**: una función, una regla, una rama de decisión |
| **Suite completa primero** | un único `test(...)` con TODOS los criterios en rojo → `feat(...)` que los pone en verde | Cuando **una sola unidad de implementación satisface varios criterios a la vez** y no puede partirse: una migración, un bloque DDL, un artefacto generado |

La segunda no es una relajación de la primera: es más estricta en lo que importa, porque exige
que **todos** los criterios estén escritos y en rojo antes de existir una línea de implementación.
Lo que no puede hacerse es mezclarlas: aplicar la forma por criterio a un RFC cuya implementación
es atómica produce commits de test **posteriores** a la implementación que ya los satisfacía, y
eso es indistinguible —para el Auditor y para `git log`— de haber escrito los tests al final.

**Cómo se decide, antes de empezar:** si revertir la implementación de un criterio dejara en rojo
también a otros criterios, esos criterios comparten unidad de implementación y van juntos en la
forma de suite completa.

> **Por qué está escrito.** ADU-PROCESO §3 y el prompt del Desarrollador exigen "la suite de tests
> en rojo, en su propio commit"; §6.1 de este RFC ilustra pares `test`/`feat` por criterio. Ambas
> lecturas eran defendibles y el contrato no decía cuál correspondía a cada caso. Elegir la forma
> equivocada no era indisciplina del Desarrollador: era una ambigüedad del contrato.

#### 6.1.2 Criterio ya satisfecho por un RFC anterior (normativo)

Un RFC puede declarar como criterio una invariante que **otro RFC ya entregó**. No es duplicación
descuidada: es lo que hace que el contrato de cada componente sea legible sin abrir los cinco
documentos anteriores. RFC-0017 CA-8 exige que falte `OPENAI_API_KEY` impida el arranque, y eso ya
era cierto desde RFC-0011 CA-0'.

Ahí **no hay nada que poner en rojo**, porque el código correcto ya está fusionado. Exigir el par
`test`/`feat` obligaría a una de dos cosas, las dos peores que la brecha: romper deliberadamente
código que funciona para volver a arreglarlo, o escribir un test que no prueba lo que dice.

**Evidencia sustituta, y son las tres juntas:**

| Evidencia | Cómo la comprueba el Auditor |
| :--- | :--- |
| El criterio se declara en el Informe como heredado, nombrando **qué RFC lo entregó** | Lectura del Informe de Implementación |
| Existe un test que lo formaliza bajo el nombre que pide el criterio | El archivo y la prueba existen |
| **La reversión lo pone en rojo** (TDD-3, §6.3), verificada y documentada en el mensaje del commit del test | Revertir la implementación heredada y ejecutar esa prueba |

La tercera es la que hace el trabajo. Un test escrito sobre comportamiento heredado es
exactamente donde más barato resulta escribir uno que pase sin probar nada: por eso aquí la
reversión no es la comprobación más fuerte de las tres, es **la única que cuenta**, y no se da por
buena porque el Informe la afirme.

Fuera de este caso la excepción no existe: si el criterio exige código nuevo, va con su par
`test`/`feat` como cualquier otro.

> **Por qué es una regla y no una excepción firmada.** Es la tercera vez que aparece esta forma
> —tras §6.2.1 (el CI no existía aún) y §6.1.1 (una implementación satisface varios criterios)— y
> volverá a aparecer cada vez que un RFC reafirme una invariante de otro, que es algo que este
> proyecto hace a propósito. ADR-0011 lo dice sin rodeos: un hallazgo cuya causa es una
> contradicción del contrato se arregla corrigiendo el contrato, no firmando excepciones, porque
> lo contrario convierte la excepción en el mecanismo por defecto.

### 6.2 Rojo registrado en CI (fuerte)

El CI se ejecuta en **cada push**, no solo al abrir el PR. El commit que solo añade tests debe
tener una ejecución **fallida** registrada, y el siguiente commit una ejecución en verde. El
Auditor consulta el historial de ejecuciones del PR y comprueba esa transición rojo → verde por
cada criterio.

Un PR cuyo primer commit ya está en verde es un PR sin TDD, y es un hallazgo **Mayor**.

**Condición operativa 1 (normativa): cada commit del par se publica solo.** El CI corre en cada
*push*, pero la ejecución queda adjunta al `HEAD` de ese *push*, **no a cada commit que el push
contiene**. Un par rojo → verde cuyos dos commits viajan juntos deja al primero sin ejecución
propia: el rojo no queda registrado en ninguna parte, y el verde que sí existe pertenece a otro
`SHA`. Por eso cada commit del par se publica en su propio *push*, sin nada encolado detrás.

La comprobación es mecánica y no admite interpretación — se consulta por `SHA`, no por la vista
de *checks* del PR, que muestra el estado del `HEAD` y no dice a qué commit pertenece:

```bash
gh api repos/<owner>/<repo>/commits/<sha>/check-runs --jq '.check_runs[] | {name, conclusion}'
```

Una respuesta vacía para el commit de implementación significa que ese commit no tiene evidencia,
por verde que esté el PR. Es hallazgo **Bloqueante**, y la corrección es rehacer la transición,
no argumentar que el `HEAD` está en verde.

**Condición operativa 2 (normativa).** Un `workflow` con `on: pull_request` no registra nada
mientras el PR no exista: los *pushes* previos a abrirlo no dejan ejecución. Por eso la rama se
publica y el PR se abre **en borrador antes del primer commit de test**, no al terminar. Un PR
abierto al final produce una única ejecución, verde, sobre el `HEAD` final — y esa ejecución no
es evidencia de nada. Abrir tarde el PR no es un detalle de flujo de trabajo: destruye la
evidencia que exige esta misma sección.

#### 6.2.1 Excepción de arranque (aplica una sola vez por repositorio)

Esta sección **presupone que el CI ya existe** — de ahí que RFC-0014 declare `Depende de:
RFC-0008`. Cuando el PR auditado es precisamente el que **introduce** ese CI, §6.2 se vuelve
imposible de satisfacer por construcción: no hay *runner* donde los commits de test pudieran
haber corrido en rojo, porque el *runner* se crea en ese mismo PR. Exigirlo ahí es exigir que la
evidencia preceda al mecanismo que la produce.

En ese caso — y **solo** en ese caso — la evidencia sustituta admisible es la conjunción de las
tres:

| Evidencia sustituta | Cómo la comprueba el Auditor |
| :--- | :--- |
| Orden de commits íntegro (§6.1), sin *squash* | `git log --reverse --oneline` sobre el rango del PR |
| Reversión pone el test en rojo (TDD-3, §6.3) | Revertir la implementación de una muestra de criterios y ejecutar la suite |
| CI verde sobre el `HEAD` final, con la suite real | Ejecución registrada del *workflow* que el propio PR introduce |

Fuera del PR que introduce el CI, esta excepción **no existe**: a partir del PR siguiente, la
ausencia de la transición rojo → verde vuelve a ser un hallazgo **Mayor**, y la causa ya no puede
ser la falta de CI sino haber abierto el PR tarde, que es responsabilidad del Desarrollador.

> **Por qué está escrito aquí y no resuelto caso por caso.** Un hallazgo cuya causa es una
> contradicción del propio contrato no se arregla firmando excepciones: se arregla corrigiendo el
> contrato. Lo contrario convierte la excepción en el mecanismo por defecto, que es exactamente
> el antipatrón que ADU existe para cortar.

#### 6.2.2 Reparación por regresión deliberada (normativo)

Un criterio puede llegar a la auditoría con el test **posterior** a la implementación y sin que
§6.1.2 lo ampare, porque el código no viene de un RFC anterior sino del propio PR. Ahí no hay
excepción que invocar: el orden se rompió. Pero el test suele ser correcto y el código también
—lo único que falta es la evidencia—, así que la reparación admisible es producirla: **romper
deliberadamente el código correcto, registrar el rojo, y restaurarlo.**

Condiciones, y son las cinco juntas:

| Condición | Cómo la comprueba el Auditor |
| :--- | :--- |
| No hay excepción §6.1.2 aplicable — el código es de este PR, no heredado | `git log --diff-filter=A` sobre el archivo implicado |
| La regresión elimina **el mecanismo que el criterio nombra**, no un detalle adyacente | El *diff* del commit rojo revierte la línea o el bloque que implementa esa invariante |
| El rojo falla **en la aserción que formaliza el criterio**, y todo fallo adicional es cascada de ese | `short test summary info` del registro del CI: una raíz, más los tests que solo fallan porque la suite falló (§6.2.3) |
| Rojo y verde tienen ejecución propia por `SHA` (§6.2, condición operativa 1) | `gh api .../commits/<sha>/check-runs` sobre los dos |
| El Informe la declara **como reparación**, nombrando el par original que sustituye | Lectura del Informe |

> **Por qué la condición 2 cambió de forma.** Decía «el rojo falla en todas las aserciones del
> test, no en la primera», y eso **no se puede satisfacer con `pytest`**: un `assert` que falla
> lanza `AssertionError` y termina la función ahí mismo, así que nunca se observa más de un fallo
> por función. La forma se aplicó cinco veces —PR #35 (CA-1, CA-12) y PR #52 (CA-8, el literal
> `actual`, CA-3)— y las cinco rompieron **una** aserción. Las cinco se aceptaron, correctamente.
> Escribí una condición que la práctica tuvo que ignorar por imposible, y un Auditor que la
> leyera al pie de la letra habría rechazado una reparación válida. Lo que la condición quería
> impedir sigue impedido, pero ahora por la vía comprobable: que la regresión toque el mecanismo
> que el criterio nombra, no un detalle adyacente que produzca un rojo barato.

**Esto no es una forma alternativa de hacer TDD.** Es una reparación, y la diferencia no es
retórica: si se admite como forma normal, cualquiera puede implementar primero **siempre** y
fabricar el par rojo → verde al final. El resultado se ve idéntico en `git log` y no prueba nada
—el test nunca guio el diseño, solo lo describió cuando ya estaba escrito—, que es precisamente
lo que §6 existe para impedir.

De ahí la lectura que el Auditor debe hacer: **la reparación se cuenta, no solo se acepta.** Un
PR con alguna reparación declarada entre varios criterios llevados por ciclo directo es un PR con
un tropiezo corregido. Un PR donde la reparación es la vía por la que llegó la mayoría de los
criterios no es un PR reparado: es un PR hecho sin TDD al que se le construyó la evidencia
después, y la reparación no lo redime — hallazgo **Mayor** sobre el PR completo.

> **Por qué se escribe en vez de resolverse en el PR.** Esta forma se usó y se aceptó en PR #35
> (RFC-0017 CA-1 y CA-12) sin estar en ninguna parte, y eso deja el peor de los dos mundos: el
> Desarrollador que la necesite no sabe que existe, y el que abuse de ella no tiene nada que se lo
> impida. Es la cuarta vez que una forma recurrente aparece primero como acuerdo dentro de un PR
> —tras §6.2.1, §6.1.1 y §6.1.2—; ADU-PROCESO ya dice que una decisión del Arquitecto se
> materializa en el RFC o en un ADR, nunca en un acuerdo verbal dentro del PR.

#### 6.2.3 Fallo raíz y fallo en cascada (normativo)

Un rojo de §6.2.2 casi nunca produce **un** fallo. La suite contiene tests que afirman sobre la
suite misma —`test_tasks.py::test_invoke_test_succeeds` ejecuta `invoke test` como subproceso y
comprueba que sale en verde—, y esos se ponen rojos **porque** el fallo raíz existe, no porque la
regresión los haya alcanzado.

Por eso el recuento de fallos no se lee en bruto:

| Tipo | Qué es | Cómo lo distingue el Auditor |
| :--- | :--- | :--- |
| **Raíz** | El test cuya aserción formaliza el criterio | Aparece en `short test summary info` con la aserción del criterio en el mensaje |
| **Cascada** | Un test que solo falla porque la suite falló | Su fallo *contiene* el resumen del fallo raíz, o ejecuta la suite como subproceso |

La reparación de CA-3 en PR #52 lo muestra en los dos *jobs* del mismo `SHA` (`5ba9537`):

```
unit-windows       1 failed, 63 passed    -> solo la raíz
integration-linux  2 failed, 118 passed   -> la raíz + test_invoke_test_succeeds
```

Es el mismo rojo visto desde dos *jobs* con distinto alcance de recolección. Contar «2 fallos» y
concluir que la regresión no fue quirúrgica es leer mal la evidencia; contar «1 fallo» mirando
solo `unit-windows` es leer bien por casualidad.

**Lo que sí es un hallazgo** es un fallo adicional que no sea ninguno de los dos: un test que se
pone rojo porque la regresión alcanzó comportamiento que el criterio no nombra. Eso significa que
el mecanismo revertido servía a más de un criterio, y entonces la reparación no prueba lo que
dice — se rehace acotando la regresión.

> **Por qué está escrito.** Nadie lo había nombrado, y toda reparación por regresión deliberada
> lo produce por construcción desde que existe `test_invoke_test_succeeds`. Salió al verificar el
> registro de CI de `5ba9537` mientras redactaba la corrección de la condición 2 — no como
> hallazgo de auditoría, sino porque estuve a punto de escribir «y el resto de la suite sigue
> verde», que es falso en `integration-linux` y habría dejado una condición que ni mi propia
> reparación cumple.

### 6.3 Reversión: qué evidencia la satisface (normativo)

**TDD-3 —la comprobación central del proceso— no estaba en este RFC.** Vivía solo en
`PROMPT-AUDITOR.md`, y este documento se limitaba a referenciarla (§6.1.2, §6.2.1) como si
estuviera definida en algún sitio. Lo está ahora.

La comprobación es esta: el Auditor elige **tres criterios al azar**, revierte la implementación
de cada uno y ejecuta su test. Si alguno sigue en verde, ese test no probaba nada, y el veredicto
es FAIL por muy alta que sea la cobertura.

**La elección al azar es del Auditor y no se negocia.** Es lo único que impide que se compruebe
solo lo que alguien preparó para ser comprobado. Todo lo que sigue es sobre *cómo* se obtiene la
evidencia de un criterio ya elegido, nunca sobre *qué* criterios se eligen.

Para el criterio elegido, cualquiera de estas tres vale, en orden de fuerza:

| Vía | Qué es | Fuerza |
| :--- | :--- | :--- |
| **Reversión ya registrada en CI** | Existe un commit del propio PR cuyo **rojo aislado por `SHA`** demuestra que ese test detecta la ausencia de ese código (§6.2.2) | **La más fuerte.** No la produce el Auditor ni el Desarrollador: la registra el CI. Es no repudiable y cualquiera la vuelve a comprobar con `gh api repos/<owner>/<repo>/commits/<sha>/check-runs` |
| **Reversión ejecutada** | El Auditor revierte con `git` —*worktree* aparte o `git stash`— y corre el test | Fuerte. Requiere un entorno que lo permita |
| **Reversión mental** | El Auditor lee el *diff* y razona qué test se rompería al quitar esa implementación | Suficiente cuando las otras dos no están disponibles. **Se declara como tal en el informe** |

La primera existe porque §6.2.2 la produce por diseño: una reparación por regresión deliberada
**es** una reversión ejecutada y registrada. Exigir que el Auditor la repita localmente para darla
por buena es pedir una copia más débil de una prueba que ya está en el historial.

**`NO VERIFICABLE` se reserva para cuando ninguna de las tres es posible**, y entonces sí impide
aprobar. Declararlo teniendo la reversión mental disponible confunde «no pude usar mi herramienta
preferida» con «no hay evidencia».

> **Por qué está escrito.** La auditoría de PR #44 declaró TDD-3 `NO VERIFICABLE` porque el
> entorno no permitió crear un *worktree*, teniendo delante tres pares rojo→verde en CI —
> producidos por §6.2.2, que se escribió dos rondas antes— y teniendo autorizada la reversión
> mental desde siempre. No fue un error de criterio del Auditor: negarse a aprobar lo que no
> comprobó es exactamente su trabajo. Fue que este RFC nunca le dijo qué hacer con la evidencia
> que ya tenía delante. Cuando escribí §6.2.2 no conecté que generaba, por diseño, la evidencia
> que TDD-3 pide.

#### 6.3.1 La comprobación también es del Desarrollador, antes de abrir el PR (normativo)

§6.3 describe TDD-3 como algo que hace el Auditor. Lo es. Pero **el Desarrollador la corre sobre
sí mismo antes de abrir el PR**, y eso hasta ahora vivía solo en su prompt.

No es una repetición de trabajo: el Auditor elige tres criterios **al azar** —esa elección no se
negocia, §6.3— mientras que el Desarrollador la pasa sobre **todos** los que entrega. Encontrar
ahí un test que no prueba nada es barato; encontrarlo en la auditoría cuesta una ronda entera.

**El resultado se declara en el Informe de Implementación**, con los criterios comprobados y lo
que salió. Un Informe que no la menciona es un Informe que no la corrió.

**Cómo se lee una reversión que vuelve verde.** No significa «el test está bien». Significa que
hay que averiguar por qué, y hay dos causas recurrentes que no son obvias:

| Trampa | Qué pasa | Cómo se sale |
| :--- | :--- | :--- |
| **El `except` amplio se traga la señal del doble** | Un doble que avisa lanzando queda neutralizado si el código bajo prueba captura `Exception`: el fallo de la aserción se convierte en un resultado que pasa | Afirmar el estado **exacto** que el criterio exige, nunca `!= X` |
| **Dos mecanismos redundantes** | Revertir uno deja el otro cubriendo el hueco, y el test no se entera | Revertirlos **juntos**; si entonces enrojece, el test vale y la redundancia se declara |

> **Por qué está escrito.** Es el mismo defecto que motivó §6.3, en espejo: entonces TDD-3 vivía
> solo en `PROMPT-AUDITOR.md` y este RFC la referenciaba como si estuviera definida en algún
> sitio; ahora la mitad del Desarrollador vivía solo en `PROMPT-DESARROLLADOR-TDD.md`. Y esta vez
> hay evidencia de que importa: en PR #58 esa autocomprobación encontró **dos** criterios cuyos
> tests seguían verdes con la implementación revertida —uno por cada trampa de la tabla—, y los
> dos se corrigieron sin tocar producción antes de que la auditoría los viera. Un prompt puede
> cambiarse sin que nadie lo note; un RFC no.

### 6.4 Prueba de mutación

La evidencia más fuerte no es el orden: es que **el test detecte la ausencia del código**. Sobre
los módulos críticos se ejecuta mutación:

```bash
mutmut run --paths-to-mutate app/retrieval/,app/core/security.py,app/ingestion/chunker.py
```

| Módulo | Umbral de mutantes eliminados |
| :--- | :--- |
| `app/retrieval/` (RRF, umbral, diversificación) | ≥ 90 % |
| `app/core/security.py` (API Key, roles) | ≥ 95 % |
| `app/ingestion/chunker.py` | ≥ 85 % |
| Resto de `app/` | No se exige |

Se limita a esos tres porque la mutación es cara y porque son los módulos donde un fallo es
silencioso o grave. Corre en el job nocturno de `main`, no en cada PR.

**Por qué importa:** un test que pasa con la implementación *y* con la implementación mutada no
está probando nada. La mutación es lo único que distingue una suite real de una suite de adorno,
y es la razón por la que la cobertura por sí sola es una métrica engañosa.

## 7. Prohibiciones

Cada una es un hallazgo del Auditor con la severidad indicada.

| # | Prohibido | Por qué | Severidad |
| :--- | :--- | :--- | :--- |
| P-1 | `assert result is not None` como única afirmación sobre lógica de negocio | No distingue una implementación correcta de una que devuelve un objeto vacío | Mayor |
| P-2 | Doblar el propio sujeto bajo prueba | El test verifica el doble, no el código | Mayor |
| P-3 | Escribir el test leyendo la implementación | Codifica el comportamiento actual, incluidos sus errores | Mayor |
| P-4 | Tests que afirman sobre el texto exacto que produce un LLM | No determinista: rojo intermitente que se acaba desactivando | Bloqueante |
| P-5 | `pytest.mark.skip` o `xfail` sin enlace a una incidencia abierta | Un test desactivado sin traza desaparece para siempre | Mayor |
| P-6 | Tests que dependen del orden de ejecución o de estado compartido | Falsos verdes y falsos rojos | Mayor |
| P-7 | `time.sleep()` para sincronizar | Lentitud e intermitencia | Menor |
| P-8 | Aumentar la cobertura con tests que no afirman nada | Convierte la métrica en teatro | Mayor |
| P-9 | Modificar un test para que pase, en vez de arreglar el código | Invierte la relación entre especificación e implementación | Bloqueante |
| P-10 | Fechas, UUID o aleatoriedad sin fijar | Rojo intermitente | Menor |
| P-11 | Cualquier prueba automática que llame a una **API de pago** (OpenAI, Anthropic) | Se ejecuta en cada `invoke test`, cada *push* y los dos *jobs* de CI: el gasto se multiplica por la frecuencia. Y una prueba que depende de un tercero deja de medir nuestro código — se pone roja cuando el proveedor falla, y la reacción es desactivarla (ADR-0012) | Bloqueante |

Sobre **P-9**: cambiar un test es legítimo **solo** cuando el criterio de aceptación del RFC ha
cambiado, y entonces el RFC se modifica primero. Un test modificado en el mismo commit que la
implementación que estaba fallando es un hallazgo Bloqueante automático.

Sobre **P-11**: la excepción es la **suite de evaluación** (RFC-0009), cuya razón de ser es medir
el sistema real y que por eso sí gasta — a mano o en el *job* nocturno, nunca en el bucle de
desarrollo. La barrera es estructural además de normativa: el CI **no tiene credenciales de ningún
proveedor**, así que una prueba que llame de verdad no puede pasar. Añadir una clave a los
*secrets* del repositorio para "poder probar de verdad" desactiva esa barrera sin que nadie lo
note, y es lo que ADR-0012 existe para impedir.

## 8. Cobertura

| Ámbito | Mínimo |
| :--- | :--- |
| Global de `app/` | 80 % |
| `app/retrieval/` (fusión, umbral, diversificación, embedder) | 100 % de ramas |
| `app/core/security.py` | 100 % de ramas |
| `app/ingestion/chunker.py` e `indexer.py` | 95 % |
| `app/providers/` (fábricas y validación) | 95 % |

La cobertura es una condición **necesaria y notoriamente insuficiente**: un módulo al 100 %
puede no probar nada (P-8). Por eso los tres módulos críticos llevan además umbral de mutación
(§6.4). Cuando las dos métricas discrepan, manda la de mutación.

## 9. Fixtures y dobles compartidos

Viven en `tests/fakes/` y son parte del contrato, no utilidades sueltas:

| Doble | Sustituye a | Comportamiento |
| :--- | :--- | :--- |
| `FakeEmbedder` | `Embedder` | `sha256(texto) → vector normalizado` de la dimensión configurada (RFC-0012 §4.2) |
| `FakeModel` | Proveedor LLM | Guion de respuestas y llamadas a herramientas fijado por el test |
| `ephemeral_db` | PostgreSQL | Base efímera con migraciones aplicadas; `TEST_DB_MODE` decide el origen (RFC-0011 §8) |
| `frozen_clock` | `now()` | Tiempo fijo para hacer deterministas cuotas y retención |
| `corpus_min` | `corpus/cv.md` | Corpus de 12 fragmentos con un caso de cada `chunk_type` |
| `corpus_poisoned` | — | Corpus con instrucciones inyectadas, para RFC-0009 §5 |

`FakeModel` es la pieza que hace testeable la capa de agente: permite afirmar *cuántas veces* y
*con qué argumentos* se llamó a una herramienta, que es lógica propia, sin afirmar nada sobre el
texto generado, que no lo es.

## 10. Criterios de aceptación de este RFC

| # | Criterio | Verificación |
| :--- | :--- | :--- |
| CA-1 | `pytest -m unit` termina en menos de 2 minutos y no abre sockets | Medición + `pytest-socket` en modo bloqueo para el marcador `unit` |
| CA-2 | Ningún test unitario llama a un LLM o embedder real | `pytest-socket` + revisión de fixtures |
| CA-3 | La cobertura cumple los mínimos de §8 por ámbito | `pytest --cov` con `fail_under` por paquete |
| CA-4 | `mutmut` alcanza los umbrales de §6.4 en los tres módulos críticos | Job nocturno |
| CA-5 | Existen los seis dobles de §9 y están usados | Inspección + uso en la suite |
| CA-6 | Toda la suite pasa dos veces seguidas y en orden aleatorio | `pytest -p no:randomly` vs `pytest --randomly-seed=…` |
| CA-7 | No hay `skip`/`xfail` sin enlace a incidencia | `grep` + revisión |
| CA-8 | El historial del PR muestra commit de test antes que el de implementación en cada criterio | `git log --reverse` |
| CA-9 | El CI registra una ejecución roja en el commit de tests de cada criterio, **adjunta a ese `SHA`** | `gh api repos/<owner>/<repo>/commits/<sha>/check-runs` por commit del par — no la vista de *checks* del PR, que informa del `HEAD` (§6.2, condición operativa 1) |
| CA-10 | Toda reparación por regresión deliberada está declarada como tal, y no son la vía de la mayoría de los criterios del PR | Informe de Implementación + recuento contra los criterios llevados por ciclo directo (§6.2.2) |
| CA-11 | El informe de auditoría resuelve TDD-3 por alguna de las tres vías de §6.3, o justifica que ninguna era posible. Si usó la reversión mental, lo declara | Lectura del informe: `NO VERIFICABLE` solo es admisible si las tres vías estaban cerradas |
| CA-12 | El Informe de Implementación declara el resultado de la autocomprobación por reversión sobre los criterios que entrega (§6.3.1) | Lectura del Informe: si no la menciona, no la corrió |

## 11. Riesgos

| Riesgo | Mitigación |
| :--- | :--- |
| TDD ceremonial: tests escritos después y ordenados a posteriori | Rojo registrado en CI (§6.2) + mutación (§6.4) |
| La reparación de §6.2.2 se vuelve la vía normal: implementar primero y fabricar el par rojo → verde al final | Se declara en el Informe y **se cuenta**: si es la vía de la mayoría de los criterios, es Mayor sobre el PR completo (§6.2.2) |
| La vía 1 de §6.3 se lee como «el Desarrollador elige qué se comprueba» y TDD-3 se vuelve decorativo | La elección de los tres criterios sigue siendo del Auditor y al azar. La vía 1 solo aplica al criterio **ya elegido**; si no tiene reversión registrada, se usa la 2 o la 3 (§6.3) |
| Intentar hacer TDD del LLM ⇒ tests intermitentes que se desactivan | Frontera de §4 + prohibición P-4 + suite de evaluación como el sitio correcto |
| La suite se vuelve lenta y se deja de ejecutar en local | Presupuesto por nivel (§5) + prohibición de IO en unitarias |
| Cobertura alta y calidad baja | Mutación en los módulos críticos; manda la mutación |
| El Desarrollador amplía alcance "porque el test lo permitía" | Verde mínimo (§3) + alcance cerrado del RFC (ADU-PROCESO §2) |

## Contrato de auditoría (gate ADU)

| # | Comprobación | Cómo se verifica | Severidad si falla |
| :--- | :--- | :--- | :--- |
| A-1 | Cada criterio de aceptación del RFC tiene al menos un test que lo codifica | Mapa criterio → test en el Informe de Implementación | Bloqueante |
| A-2 | El commit de test precede al de implementación en cada criterio | CA-8 | Mayor |
| A-3 | El CI registró rojo en el commit de tests y verde en el siguiente | CA-9 | Mayor |
| A-4 | Ningún test unitario toca red, disco o base de datos | CA-1, CA-2 | Mayor |
| A-5 | Ningún test afirma sobre el texto literal de un LLM | Búsqueda de aserciones sobre `answer` en `tests/unit/` | Bloqueante |
| A-6 | Revertir la implementación de un criterio pone su test en rojo | Prueba puntual sobre 3 criterios elegidos por el Auditor | Bloqueante |
| A-7 | No hay tests modificados en el mismo commit que la implementación que fallaba | `git show` sobre los commits del PR | Bloqueante |
| A-8 | Se cumplen los mínimos de cobertura por ámbito | CA-3 | Mayor |
| A-9 | Los umbrales de mutación se cumplen en los tres módulos críticos | CA-4 | Mayor |
| A-10 | No hay `skip`/`xfail` sin incidencia enlazada | CA-7 | Menor |
| A-11 | La suite es estable: dos ejecuciones seguidas dan el mismo resultado | CA-6 | Mayor |
| A-12 | El Desarrollador corrió la reversión sobre sus propios criterios y lo declara en el Informe | CA-12 | Mayor |

**A-6 es la comprobación central de este RFC.** El Auditor elige tres criterios al azar, revierte
la implementación correspondiente y ejecuta su test. Si alguno sigue en verde, ese test no estaba
probando nada, y el veredicto es `FAIL` por muy alta que sea la cobertura.
