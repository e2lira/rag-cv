# ADR-0017 — El agente se construye por turno, sobre un modelo compartido

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aceptada |
| **Fecha** | 2026-08-24 |
| **Decide** | Arquitecto |
| **RFCs afectados** | RFC-0004 (§6, §7), RFC-0005 (§4, CA-19) |
| **Severidad del defecto que corrige** | Bloqueante — fuga de datos entre usuarios, presente en `main` |

## Contexto

El Desarrollador paró al escribir la guarda de CA-19 en la PR #85 y escaló. Lo que encontró no es
un criterio sin cubrir: es un defecto de privacidad **ya fusionado en `main`**.

**RFC-0004 §6 se contradice a sí mismo cuando se lo lee contra el SDK que este proyecto usa.**
La cláusula dice dos cosas en el mismo párrafo:

> «**El agente se construye una vez por proceso** (en el `lifespan` de FastAPI) y se reutiliza;
> el estado conversacional **no** se guarda en el objeto agente, sino que se pasa como historial
> en cada invocación (§7). Esto evita fugas de contexto entre usuarios distintos, que es el
> error más caro de esta arquitectura.»

La regla es «uno por proceso». La razón que la justifica es «que el estado no viva en el objeto».
Con `strands-agents 1.53`, **la regla garantiza justo lo que la razón quería evitar**: el objeto
`Agent` acumula `self.messages` en cada invocación, así que un agente por proceso es un agente que
va concatenando las conversaciones de todos los usuarios que pasen por él.

No es una lectura del código fuente ni una deducción: son cinco comprobaciones medidas sobre
`strands-agents 1.53.0`, con el `ScriptedModel` de RFC-0004 §12.

| # | Escenario | Resultado medido |
| :--- | :--- | :--- |
| 1 | Agente compartido, dos turnos sucesivos | `messages` pasa de 2 a 4; el turno 2 recibe la pregunta del turno 1 |
| 2 | Agente compartido, dos turnos **solapados** | `ConcurrencyException: Agent is already processing a request. Concurrent invocations are not supported.` |
| 3 | Un agente por turno | Aísla. Coste de construcción: **1,66 ms** |
| 4 | Modelo compartido + un agente por turno | Concurrente sin error, y sin fuga |
| 5 | `Agent(messages=historial)` | Precarga el historial correctamente |

La comprobación 2 merece un aviso: la primera vez dio «sin error», y era **falso**. El
`ScriptedModel` sin demora no cede el control, así que `asyncio` serializaba las dos invocaciones y
nunca llegaban a solaparse. Con `demora=0.15` la excepción aparece siempre. Una prueba de
concurrencia que no se solapa no prueba concurrencia.

### Los tres defectos que esto produce hoy en `main`

1. **Fuga de contexto entre usuarios.** La conversación de quien pregunta primero llega íntegra al
   turno de quien pregunta después. RFC-0004 §6 la llama, con sus palabras, «el error más caro de
   esta arquitectura». En un despliegue público —que es exactamente lo que RFC-0020 va a hacer—
   significa que un visitante lee lo que preguntó otro.
2. **Los resultados de herramientas se reenvían.** RFC-0004 §7 lo prohíbe explícitamente
   («los resultados de herramientas de turnos anteriores **no** se reenvían»), y en el transcript
   observado viajan los bloques `toolResult` completos. Multiplica los tokens de entrada por turno
   y arrastra contexto obsoleto tras una reindexación.
3. **`load_history()` no la llama ningún código de producción.** Existe en `app/agent/memory.py`,
   tiene sus pruebas, y nadie la invoca. La continuidad que parecía funcionar **era la fuga**: no
   había memoria, había contaminación.

El tercero es el que más merece detenerse. La PR #78 pasó auditoría con esa función escrita,
probada de forma aislada y jamás conectada. Una función con cobertura propia y cero llamadas de
producción no la marca ninguna métrica de cobertura: la línea está cubierta, y el sistema no la usa.

### CA-5 existe, pasa, y no protege nada

Lo anterior sería un descuido. Esto es un problema de método, y es más grave.

**RFC-0004 ya tiene el criterio.** CA-5 dice, literalmente, «Dos conversaciones distintas no
comparten historial», y lo verifica `test_agent.py::test_no_context_bleed`. Ese criterio está
marcado como cumplido desde la PR #78. La fuga existe igual.

La prueba **nunca construye un `Agent`**:

```python
historial_a = load_history(conn, conversacion_a)
assert "Hola B" not in contenidos
```

Lo que verifica es que `load_history` filtra por `conversation_id` — o sea, que una cláusula
`WHERE` funciona. Y funciona. Pero CA-5 no dice «`load_history` filtra por conversación»: dice
**«dos conversaciones distintas no comparten historial»**, que es una afirmación sobre el sistema
entero. Entre las dos frases cabe justo el defecto: la función es correcta, el sistema filtra, y el
criterio figura en verde.

Un criterio enunciado sobre el sistema y verificado sobre un componente aislado **no es un criterio
verificado**. Es una afirmación sobre la parte, con el nombre de la afirmación sobre el todo.

## Decisión

**El modelo se construye una vez por proceso. El agente se construye una vez por turno, alrededor
de ese modelo, con el historial precargado.**

- `build_model(settings)` sigue ejecutándose en el `lifespan` (RFC-0021 §5): es lo que resuelve
  credenciales y cliente del proveedor, y es lo que no conviene repetir.
- `build_agent()` acepta el modelo ya construido y se invoca **por turno**, con
  `messages=load_history(conn, conversation_id)`.
- Ningún objeto de vida larga guarda estado conversacional. El agente vive lo que vive el turno.

**Esto no relaja RFC-0004 §6: cumple su razón declarada por primera vez.** Lo que cambia es la
regla —«una vez por proceso»— que resultó ser el medio equivocado para el fin que el propio párrafo
enuncia. Se conserva el fin y se corrige el medio.

### Por qué no las alternativas

| Alternativa | Por qué no |
| :--- | :--- |
| Limpiar `agent.messages` antes de cada turno | Cierra la fuga secuencial y **no** la concurrente: dos peticiones solapadas siguen chocando con `ConcurrencyException`, y entre el `clear()` y el `stream_async()` hay una carrera que ninguna prueba determinista atrapa. Arregla el síntoma que se ve y deja el que aparece con carga. |
| Un `asyncio.Lock` alrededor del turno | Serializa **toda** la API sobre un único agente. Un turno tarda segundos: con dos usuarios concurrentes, el segundo espera al primero. Convierte un defecto de corrección en uno de rendimiento, y RNF-1 acota la latencia. |
| `ConcurrentInvocationMode.UNSAFE_REENTRANT` | El propio SDK lo llama `UNSAFE`. Permite la invocación concurrente sin resolver el estado compartido: quita la excepción que avisa y deja la fuga. |
| Un agente por proceso **y** por usuario | Estado de sesión en memoria del proceso: se pierde al reiniciar, no sobrevive a dos réplicas, y duplica la memoria de conversación que ya vive en PostgreSQL (RFC-0006). |

### El coste, dicho con el número

1,66 ms por turno. Construir el agente no toca la red —`build_model` instancia, no llama
(ADR-0012)—, y contra un turno que tarda segundos es ruido. **Este ADR no se decide por coste: se
decide por corrección.** El número está aquí para dejar constancia de que el coste no fue el
motivo de nada.

## Consecuencias

- **RFC-0004 §6 queda enmendado** (ver §13 de ese RFC). La frase «se construye una vez por proceso»
  pasa a aplicarse al **modelo**; el agente es por turno.
- **RFC-0004 §7 pasa a ser cierto.** Hoy la cláusula está escrita y no implementada; el historial
  empieza a cargarse de verdad, y sin los `toolResult`.
- **RFC-0005 CA-19 se vuelve verificable.** Mientras la continuidad la producía la fuga, cualquier
  prueba que la afirmara pasaba por la razón equivocada.
- **La PR #85 no puede cerrarse sin esto.** Su CA-19 depende de este cambio.
- **Deuda declarada:** este ADR no ordena una migración de datos ni un cambio de esquema. La
  memoria ya vive en `conversations`/`messages` (RFC-0006 §4); lo único que faltaba era leerla.

### Aviso de despliegue

**No se despliega a QA hasta que esto esté corregido.** RFC-0020 hace público el servicio, y el
defecto 1 convierte cualquier demo con dos visitantes en una filtración de la conversación del
primero al segundo. Es la única razón por la que este ADR lleva severidad Bloqueante y no Mayor.

## Cómo se verifica

La prueba que cierra esto **no puede afirmar sobre la respuesta HTTP**. Que dos turnos compartan
`conversation_id`, o que haya dos llamadas al modelo, es cierto con memoria y sin ella. Tiene que
afirmar sobre **lo que el modelo recibe**, y necesita su guarda:

1. El segundo turno de una conversación ve el texto del primero en los mensajes que le llegan al
   modelo.
2. Una conversación **distinta** no ve nada de la primera.

Sin la segunda, la primera pasa con la fuga puesta —que es exactamente lo que ocurrió—. Es la
segunda vez en esta entrega que un criterio se escapa por afirmar sobre la salida en lugar de sobre
lo que recibe el colaborador; la primera fue CA-21, donde el `200` con la base caída no distinguía
un `/healthz` que abría conexión de uno que no. **Cuando un criterio habla de una ausencia o de una
continuidad, la aserción va sobre el colaborador, no sobre la respuesta.**
