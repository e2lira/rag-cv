# ADR-0012 — Ninguna prueba automática llama a una API de pago; solo la evaluación gasta, y con presupuesto declarado

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aceptada |
| **Fecha** | 2026-08-23 |
| **Decide** | Arquitecto |
| **RFCs afectados** | RFC-0017, RFC-0018, RFC-0014, RFC-0009, RFC-0008 |

## Contexto

La PoC dejó de autoalojar modelos: los *embeddings* van por la API de OpenAI (ADR-0007) y la
generación por la de Anthropic (ADR-0008). **Las dos se facturan por token.** Hasta ahora ninguna
consumía dinero porque no había código que las llamara; el punto 3 del plan de ejecución introduce
la primera.

Nada en el corpus documental lo regula. `RFC-0014` prohíbe nueve prácticas en las pruebas
—dobles del sujeto, `assert x is not None`, `time.sleep()`— pero **ninguna menciona el coste**:

```
$ rg -n "API de pago|cuesta dinero|presupuesto de coste" docs/rfc/RFC-0014-*.md \
     docs/adu/prompts/PROMPT-DESARROLLADOR-TDD.md
(sin resultados)
```

El riesgo no es hipotético ni caro por llamada: es que **la suite se ejecuta en bucle**. Un
`OpenAIEmbedder` que llame de verdad desde una prueba unitaria se ejecuta en cada `invoke test`,
en cada *push*, y en los dos *jobs* de CI por PR. Un céntimo por ejecución es irrelevante hasta
que son mil ejecuciones, y para entonces el patrón ya está copiado en las pruebas siguientes.

Hay además un modo de fallo peor que el gasto: una prueba que depende de un tercero **deja de
medir nuestro código**. Se pone roja cuando el proveedor tiene un mal día, y la reacción natural
—desactivarla— destruye justamente la cobertura que decía aportar.

## Decisión

**Ninguna prueba automática llama a una API de pago. La evaluación sí, deliberadamente, con
presupuesto declarado.** Tres niveles, y la frontera entre ellos es verificable:

| Nivel | Llama a la API | Cómo se garantiza |
| :--- | :--- | :--- |
| Pruebas unitarias | **Nunca** | `FakeEmbedder` y el doble del cliente HTTP. Una unitaria que abre un socket ya es hallazgo Mayor (rúbrica transversal del Auditor) |
| Pruebas de integración | **Nunca contra el proveedor.** Sí contra PostgreSQL real | El contrato del proveedor se prueba contra un doble que responde como él, incluidos sus errores |
| Evaluación (RFC-0009) | **Sí** | Es su razón de ser: mide el sistema real. Se ejecuta a mano o en el *job* nocturno, nunca en el bucle de desarrollo |

**El CI no tiene credenciales de ningún proveedor, y no se le añaden.** Hoy es cierto y es
verificable:

```
$ rg -n "API_KEY|secrets\." .github/workflows/python-tests.yml
(sin resultados)
```

Esto convierte la regla en estructural en vez de disciplinaria: una prueba que llame de verdad
**no puede** pasar en CI, porque no hay clave. El día que alguien añada una clave a los *secrets*
del repositorio para "poder probar de verdad", la barrera desaparece sin que nadie lo note — por
eso queda escrito aquí y con comprobación de auditoría propia.

**El identificador del modelo se fija a una versión, no a un alias.** `RFC-0017 §5` ya lo exige
para el *embedder* y da la razón: si el proveedor mueve el modelo detrás del nombre, la salida es
otro modelo y **nada falla**. El mismo argumento aplica a la generación, donde `RFC-0018` designaba
hasta esta decisión `claude-haiku-4-5` —un alias— y publicaba su línea base en
`evals/baselines/anthropic-claude-haiku-4-5.json`. Si el alias avanza, la línea base deja de
corresponder al modelo que responde. Se fija la versión con fecha; el alias queda como
documentación de a qué familia pertenece.

**El nombre del archivo de línea base también lleva la versión**, no solo la variable:
`evals/baselines/anthropic-claude-haiku-4-5-20251001.json`. Un archivo nombrado por el alias
no distingue versiones, así que la línea base de una sobrescribiría a la de la otra — el mismo
fallo silencioso, movido del identificador al nombre del fichero.

## Alternativas consideradas

| Alternativa | A favor | En contra | Por qué se descarta |
| :--- | :--- | :--- | :--- |
| Llamadas reales en integración, con clave en CI | Prueba el contrato del proveedor de verdad, incluidos cambios que un doble no anticipa | Gasto por cada PR; pruebas rojas por causas ajenas; una clave de larga vida en los *secrets* del repositorio | El coste no es el argumento principal: es que la prueba deja de medir nuestro código y la reacción a su intermitencia es desactivarla |
| Grabación y reproducción (*cassettes* tipo VCR) | Una llamada real la primera vez, gratis después; captura la forma real de la respuesta | Los *cassettes* envejecen y nadie los regenera; se convierten en un doble con más ceremonia y menos honestidad sobre lo que ya no verifican | Aporta poco frente al doble explícito, y añade un artefacto que caduca en silencio |
| Tope de gasto en el proveedor y llamadas libres | Simple, una sola palanca | Un tope es un cortafuegos, no un diseño: cuando salta, ya se gastó, y lo que se rompe es la suite entera | Se conserva como red de seguridad, **no** como el control |
| No escribir la regla y confiar en el criterio | Cero documento que mantener | Es exactamente lo que hubo hasta hoy, y la primera integración de pago llega esta semana | La disciplina que no está escrita no se audita, y lo que no se audita en este proyecto ha reaparecido como hallazgo |

## Consecuencias

**Positivas:**

- El bucle de desarrollo es gratis y determinista. `invoke test` no depende de la red ni del saldo.
- La barrera es estructural, no disciplinaria: sin clave en CI, la prueba que llama de verdad falla.
- El gasto queda concentrado donde produce información —la evaluación— en vez de repartido en
  llamadas que nadie contabiliza.
- La línea base de evaluación sigue correspondiendo al modelo que la produjo.

**Negativas / deuda aceptada:**

- **El doble puede divergir del proveedor real sin avisar.** Si OpenAI cambia la forma de la
  respuesta, las pruebas siguen verdes y el fallo aparece en la primera ejecución real. Se acepta
  porque la evaluación de RFC-0009 es la que ejerce el camino real, y porque la alternativa
  —llamadas en cada PR— tiene un modo de fallo peor.
- **El coste de la evaluación no está presupuestado todavía.** RFC-0009 fija umbrales de calidad,
  no de gasto. Queda como brecha declarada: **corresponde a RFC-0009** cifrar el coste de una
  ejecución completa de la suite y el del juez LLM, que es el que más consume.
- Fijar la versión con fecha obliga a una actualización explícita cuando salga una nueva. Es
  deliberado: que caduque visiblemente es preferible a que cambie en silencio.

**Condición de revisión:** se reabre si aparece un entorno de pruebas gratuito del proveedor
(cuota de desarrollo sin cargo), o si la divergencia entre el doble y la API real produce dos
incidentes que la evaluación no anticipó — en ese caso el balance cambia y toca reconsiderar las
llamadas reales en integración, con presupuesto explícito.
