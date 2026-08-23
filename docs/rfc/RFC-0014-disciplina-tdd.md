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

### 6.2 Rojo registrado en CI (fuerte)

El CI se ejecuta en **cada push**, no solo al abrir el PR. El commit que solo añade tests debe
tener una ejecución **fallida** registrada, y el siguiente commit una ejecución en verde. El
Auditor consulta el historial de ejecuciones del PR y comprueba esa transición rojo → verde por
cada criterio.

Un PR cuyo primer commit ya está en verde es un PR sin TDD, y es un hallazgo **Mayor**.

### 6.3 Prueba de mutación (la definitiva)

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

Sobre **P-9**: cambiar un test es legítimo **solo** cuando el criterio de aceptación del RFC ha
cambiado, y entonces el RFC se modifica primero. Un test modificado en el mismo commit que la
implementación que estaba fallando es un hallazgo Bloqueante automático.

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
(§6.3). Cuando las dos métricas discrepan, manda la de mutación.

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
| CA-4 | `mutmut` alcanza los umbrales de §6.3 en los tres módulos críticos | Job nocturno |
| CA-5 | Existen los seis dobles de §9 y están usados | Inspección + uso en la suite |
| CA-6 | Toda la suite pasa dos veces seguidas y en orden aleatorio | `pytest -p no:randomly` vs `pytest --randomly-seed=…` |
| CA-7 | No hay `skip`/`xfail` sin enlace a incidencia | `grep` + revisión |
| CA-8 | El historial del PR muestra commit de test antes que el de implementación en cada criterio | `git log --reverse` |
| CA-9 | El CI registra una ejecución roja en el commit de tests de cada criterio | Historial de ejecuciones del PR |

## 11. Riesgos

| Riesgo | Mitigación |
| :--- | :--- |
| TDD ceremonial: tests escritos después y ordenados a posteriori | Rojo registrado en CI (§6.2) + mutación (§6.3) |
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

**A-6 es la comprobación central de este RFC.** El Auditor elige tres criterios al azar, revierte
la implementación correspondiente y ejecuta su test. Si alguno sigue en verde, ese test no estaba
probando nada, y el veredicto es `FAIL` por muy alta que sea la cobertura.
