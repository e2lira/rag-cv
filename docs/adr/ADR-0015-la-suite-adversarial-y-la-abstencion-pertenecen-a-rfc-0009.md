# ADR-0015 — La suite adversarial y la abstención pertenecen a RFC-0009; RFC-0004 las referencia, no las duplica

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aceptada |
| **Fecha** | 2026-08-24 |
| **Decide** | Arquitecto (arbitraje, ADU-PROCESO §10) |
| **RFCs afectados** | RFC-0004, RFC-0014, RFC-0009 (declarativo) |

## Contexto

PR #78 lleva **tres rondas** con el mismo hallazgo bloqueante: A-7 de RFC-0004, «faltan las pruebas
de CA-4, CA-6 y CA-7; no hay ADR aplicable». Desarrollador y Auditor no convergen, así que el
arbitraje corresponde al Arquitecto y se materializa aquí, no como acuerdo dentro del PR.

El Desarrollador diagnosticó una contradicción entre `RFC-0014 §5` (nivel adversarial con **LLM
real**, cada PR) y `RFC-0004 §12` (adversariales **con modelo falso**). La contradicción existe y
está bien vista. **Pero es un síntoma, no la causa.**

### La causa: RFC-0004 §11 duplicó tres criterios que RFC-0009 ya posee

| Criterio de RFC-0004 §11 | Dónde vive ya, con presupuesto y mecanismo |
| :--- | :--- |
| **CA-4** — abstención con contexto vacío | RFC-0009 **CA-7** (10 casos de abstención ⇒ `grounded=false` + negativa explícita), **CA-8** (contexto vacío inyecta la instrucción por código), métrica *Abstención correcta* ≥ 0.95, gate **A-6 (Bloqueante)** |
| **CA-6** — fuga del prompt de sistema | RFC-0009 §5, familias *Fuga de prompt* y *Fuga indirecta*; métrica *Fuga de prompt* = 0; gate **A-4 (Mayor)** |
| **CA-7** — inyección desde el corpus | RFC-0009 **CA-6** (`tests/adversarial/test_corpus_injection.py`), §5 familia *Inyección desde el corpus*, corpus `evals/fixtures/cv_poisoned.md`, gate **A-5 (Bloqueante)** |

Cuatro hechos confirman que es duplicación y no refuerzo deliberado:

1. **El directorio es de RFC-0009.** `tests/adversarial/` se declara en RFC-0009 §5. RFC-0004 lo
   cita sin declararlo, y no puede: el marcador `adversarial` que RFC-0014 §5 le asigna no existe
   en `pyproject.toml`, que solo declara `unit` e `integration`. Un marcador no declarado **no
   falla: se ignora en silencio**, y la prueba corre donde no debía.
2. **Dos nombres para el mismo archivo.** RFC-0004 §11 pide
   `tests/adversarial/test_prompt_injection.py`; RFC-0009 CA-6 pide
   `tests/adversarial/test_corpus_injection.py`. Es la misma prueba con dos nombres — la firma de
   que los dos documentos nunca se reconciliaron.
3. **Dos mecanismos incompatibles para la misma invariante.** RFC-0009 la mide con **LLM real**,
   juez calibrado y presupuesto declarado (USD 0.30 por PR, §6). RFC-0004 §12 dice modelo falso.
4. **Dos puntos distintos del plan.** `PLAN-DE-EJECUCION.md` asigna la suite adversarial al
   **punto 10** (RFC-0009). RFC-0004 es el **punto 8**. RFC-0004 exigía como gate de *merge* un
   artefacto que el plan entrega dos puntos después.

### La frase equivocada es mía

`RFC-0004 §12` dice hoy que las adversariales *«corren con el modelo falso […] y son gate de merge
(RFC-0009)»*. **La escribí yo** en la corrección del DoR (PR #77), para hacer §12 compatible con
ADR-0012 sin comprobar que RFC-0009 §5 ya era dueño de esa suite y ya tenía presupuesto. La frase
se contradice a sí misma en once palabras: cita a RFC-0009 como el gate mientras describe un
mecanismo que RFC-0009 no usa.

El Desarrollador tenía razón en negarse a escribir esas pruebas. Cualquiera de las dos salidas que
tenía disponibles era un defecto: con LLM real habría violado P-11 sin excepción firmada; con
modelo falso habría producido pruebas que no prueban lo que su nombre dice, porque **el guion del
doble lo escribe la propia prueba** — un modelo falso no puede «resistir» una fuga de prompt.

## Decisión

**CA-4, CA-6 y CA-7 salen del contrato de RFC-0004 y se declaran heredados por RFC-0009, que ya
los define con mecanismo y presupuesto. RFC-0004 los referencia; no los duplica ni los reimplementa
con un mecanismo más débil.**

Cinco cambios, todos en documentación:

| # | Documento | Cambio |
| :--- | :--- | :--- |
| 1 | RFC-0004 §11 | CA-4, CA-6 y CA-7 pasan a una tabla de *criterios delegados*, nombrando el criterio de RFC-0009 que los cubre. **No se renumeran**: CA-4/CA-6/CA-7 conservan su identificador y su fila, con el destino escrito |
| 2 | RFC-0004 §11 | Se añade **CA-11**, nuevo y al final: lo que sí es de esta capa —`search_cv` entrega el contenido recuperado como **dato delimitado**, sin interpretarlo ni despojarlo— y es verificable con doble porque no depende del modelo |
| 3 | RFC-0004 §12 | Se corrige la frase falsa sobre las adversariales |
| 4 | RFC-0004, contrato de auditoría | **A-7** se reescribe: deja de exigir las pruebas adversariales en este punto y pasa a exigir que la delegación esté declarada y que CA-11 exista |
| 5 | RFC-0014 §5 y §7 (P-11) | Se aclara que el nivel adversarial es **de RFC-0009**, que por tanto está dentro de la excepción de P-11, y que su marcador lo declara RFC-0009 al implementarlo |

**Lo que no cambia:** las tres invariantes siguen siendo gate obligatorio antes de PROD. No se
relaja ningún umbral: *Fuga de prompt* = 0 y *Abstención correcta* ≥ 0.95 siguen bloqueando el
*merge* en RFC-0009 §6, y A-5/A-6 de RFC-0009 siguen siendo Bloqueantes. Lo único que se mueve es
**en qué punto del plan se verifican**, y se mueve al punto donde el mecanismo existe.

## Alternativas consideradas

| Alternativa | A favor | En contra | Por qué se descarta |
| :--- | :--- | :--- | :--- |
| **Escribir las adversariales en RFC-0004 con modelo falso** | Cierra A-7 hoy; sin gasto | Un doble con guion fijo no puede demostrar resistencia: la prueba afirmaría lo que ella misma escribió. Y crea una segunda fuente de verdad para una invariante que RFC-0009 ya mide de verdad | Es teatro de cobertura (P-8) y duplica el contrato. Cierra el hallazgo sin cerrar el riesgo |
| **Escribir las adversariales en RFC-0004 con LLM real** | Verifica la invariante de verdad | Viola P-11 (Bloqueante) sin excepción firmada, y ADR-0012 deja el CI **sin credenciales** a propósito: no podría pasar. Además duplicaría el gasto que RFC-0009 ya presupuestó | Exige firmar una excepción a P-11 para hacer, peor y antes, lo que RFC-0009 ya hace |
| **Bajar CA-4/CA-6/CA-7 a Menor y mergear** | Desbloquea sin tocar contratos | Convierte en cosmético el criterio que el propio PRD llama asimétrico («ninguna alucinación es aceptable en un CV»). Y no arregla la duplicación: seguirían en dos RFC | Rebajar la severidad de un riesgo real para desbloquear un PR es exactamente lo que ADU existe para impedir |
| **Enmendar RFC-0014 §5 para que el nivel adversarial use doble** | Reconcilia §5 con RFC-0004 §12 de un plumazo | Rompe RFC-0009 §5 y §6 completos —familias, corpus envenenado, métricas, presupuesto— para salvar una frase que escribí mal. Invierte la dirección del arreglo | El documento correcto es RFC-0009; el equivocado es §12 de RFC-0004. Se corrige el equivocado |
| **Delegar a RFC-0009 (elegida)** | Una sola fuente de verdad; mecanismo real; presupuesto ya declarado; precedente directo en ADR-0014 | Deja una ventana sin gate adversarial entre el punto 8 y el punto 10 | Se acepta con mitigación y condición de reapertura declaradas abajo |

## Consecuencias

**Positivas:**

- Una sola fuente de verdad por invariante. Hoy `tests/adversarial/` tenía dos dueños y dos nombres
  para el mismo archivo; pasa a tener uno.
- El criterio se verifica donde existe el mecanismo que lo verifica. RFC-0009 ya tiene el corpus
  envenenado, el juez calibrado, las ocho familias y el presupuesto; RFC-0004 no tiene ninguno de
  los cuatro y no debería construirlos.
- Desbloquea el punto 8 sin relajar nada: ningún umbral baja, ninguna severidad se rebaja.
- Precedente consistente: es el mismo patrón que **ADR-0014** (métrica `ProviderFallbacks` diferida
  a RFC-0010 porque su mecanismo no existía todavía) y que la herencia de RFC-0013 CA-6/CA-10 hacia
  RFC-0004 ya resuelta en PR #71/#72.

**Negativas / deuda aceptada:**

- **Entre el punto 8 y el punto 10 no hay gate adversarial automático.** Es real y se acepta con
  tres mitigaciones: (a) las defensas viven en el prompt de sistema (RFC-0004 §4, secciones *FUENTE
  DE VERDAD* y *ALCANCE*) y **A-3 verifica que las cuatro secciones estén completas y sin recortes**;
  (b) CA-11 cubre la única pieza que es código nuestro —que el contenido recuperado llegue al modelo
  como dato delimitado, no como instrucción—; (c) no hay endpoint público hasta el punto 9 y no hay
  despliegue hasta el punto 11, ambos posteriores al punto 10.
- **La duplicación pudo haber existido en otros RFC y no se ha buscado sistemáticamente.** Este ADR
  corrige el caso encontrado, no audita el corpus documental entero.

**Deuda declarada que este ADR *no* resuelve, con dueño:**

> **ADR-0012 y RFC-0009 §6 se contradicen sobre dónde corre la evaluación.** ADR-0012 fija que la
> evaluación se ejecuta «a mano o en el *job* nocturno, **nunca en el bucle de desarrollo**» y que
> «**el CI no tiene credenciales de ningún proveedor, y no se le añaden**». RFC-0009 §6 corre la
> suite `pr` —25 casos + adversariales, USD 0.30— **en cada PR**, como job 7 de RFC-0008, lo que
> exige exactamente esas credenciales en CI. Las dos afirmaciones no pueden ser ciertas a la vez.
>
> No se resuelve aquí porque excede el arbitraje pedido y cambiaría el diseño de gates de RFC-0009.
> **Dueño: RFC-0009, punto 10 del plan.** Debe decidirse entonces si la suite `pr` corre en CI con
> credenciales (y ADR-0012 se enmienda), o si se mueve fuera del CI (y RFC-0009 §6 se enmienda).
> Mientras no se decida, **el punto 10 no puede darse por listo**: es su Definition of Ready.

**Condición de revisión:** se reabre si RFC-0009 se cancela, se difiere más allá del punto 10, o
pierde alguna de las tres invariantes (abstención, fuga de prompt, inyección desde el corpus) al
implementarse. En cualquiera de los tres casos, RFC-0004 se queda sin la cobertura que este ADR le
delegó y CA-4/CA-6/CA-7 deben volver a su contrato con un mecanismo propio y presupuesto explícito.
