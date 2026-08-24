# ADR-0016 — La cuota se cuenta por cubeta fija, no por ventana deslizante

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aceptada |
| **Fecha** | 2026-08-24 |
| **Decide** | Arquitecto |
| **RFCs afectados** | RFC-0005 (§7), RFC-0006 (§4.4, declarativo) |

## Contexto

El Desarrollador paró antes de implementar CA-6 y escaló: **`RFC-0005 §7` se contradice a sí mismo
en una sola frase.**

> «**Ventana deslizante** por `key_id`: `RATE_LIMIT_PER_MINUTE` (30) y `RATE_LIMIT_PER_DAY`
> (1 000). Implementación: contador en PostgreSQL con `INSERT ... ON CONFLICT` sobre una tabla de
> **cubetas** (`rate_buckets`)»

Ventana deslizante y cubetas son algoritmos distintos, y el esquema —ya fusionado en RFC-0006 §4.4,
punto 5 del plan— fija el segundo sin ambigüedad:

```sql
PRIMARY KEY (key_id, window_kind, window_start)   -- window_kind IN ('minute','day')
```

Una fila por cubeta y un contador. `increment_rate_bucket()` devuelve el contador **de la cubeta
actual**, y no hay nada en el esquema que registre el instante de cada petición.

El escalado fue correcto y la ambigüedad es real: CA-6 exige «429 con `Retry-After` **correcto**»,
y qué significa "correcto" depende del algoritmo:

| | Cubeta fija | Ventana deslizante |
| :--- | :--- | :--- |
| Ráfaga en el borde | 30 peticiones a las 10:00:59 + 30 a las 10:01:00 ⇒ **60 aceptadas en dos segundos** | Se rechazan: la ventana mira siempre 60 s hacia atrás |
| `Retry-After` | **Un hecho**: los segundos que faltan para que cierre la cubeta | Una estimación: cuándo caducarán suficientes peticiones viejas |
| Coste por petición | La sentencia que ya existe | Leer dos cubetas y ponderar, o guardar una marca por petición |

## Decisión

**La cuota se cuenta por cubeta fija: una por minuto y una por día, por `key_id`.** `RFC-0005 §7`
se corrige para decir lo que el sistema hace y para que `Retry-After` sea verificable.

Contrato preciso, que es lo que faltaba:

| Elemento | Valor |
| :--- | :--- |
| Cubeta de minuto | `window_start` truncado al minuto; tope `RATE_LIMIT_PER_MINUTE` (30) |
| Cubeta de día | `window_start` truncado al día **en UTC**; tope `RATE_LIMIT_PER_DAY` (1 000) |
| Se incrementan | **Las dos, siempre**, antes de invocar al agente |
| `429` cuando | Cualquiera de las dos supera su tope |
| `Retry-After` | Segundos enteros hasta que cierre **la cubeta que disparó el rechazo**. Si son las dos, la de día: es la que sigue bloqueando después |
| `X-RateLimit-Limit` | El tope de esa misma cubeta |
| `X-RateLimit-Remaining` | `0` en el `429`; `tope - count` en una respuesta normal |
| `X-RateLimit-Reset` | Instante de cierre de esa cubeta, en segundos Unix |

**UTC y no hora local**: una cubeta de día anclada a la zona del servidor cambia de tamaño dos
veces al año, y una cuota que dura 23 o 25 horas según el mes no es un contrato.

## Alternativas consideradas

| Alternativa | A favor | En contra | Por qué se descarta |
| :--- | :--- | :--- | :--- |
| **Cubeta fija (elegida)** | Es lo que el esquema ya fusionado soporta; una sola sentencia atómica; `Retry-After` es un hecho, no una estimación | Tolera hasta el doble del tope en el borde de la ventana | Se acepta con la deuda declarada abajo: el tope diario sigue siendo el techo de coste real |
| Contador de ventana deslizante (dos cubetas ponderadas) | Corta la ráfaga del borde; mismo esquema, sin migración | Dos lecturas por petición; `Retry-After` pasa a ser una estimación —y CA-6 pide que sea correcto—; más ramas que cubrir en un módulo con umbral alto | El problema que resuelve está acotado y es barato (ver deuda); el coste que añade cae sobre el criterio que más importa |
| Registro deslizante real (una marca por petición) | Exacto | Migración de esquema, una fila por petición y purga periódica. RFC-0006 §4.4 se diseñó explícitamente para evitarlo | Desproporcionado para 30 peticiones por minuto |
| Redis con `INCR` y `EXPIRE` | El mecanismo natural para cuotas | Una pieza más que operar en tres entornos. RFC-0005 §7 ya la descartó por eso | La razón original sigue vigente: el VPS de la PoC corre un solo proceso |

## Consecuencias

**Positivas:**

- `RFC-0005 §7` deja de contradecirse, y CA-6 pasa a ser verificable: `Retry-After` tiene un valor
  calculable y comprobable, no una interpretación.
- Cero cambios de esquema y cero código nuevo en `app/core/rate_buckets.py` para el conteo: la
  sentencia atómica que ya existe es exactamente la que hace falta.
- La decisión respeta RFC-0001 §62: el cálculo de cubetas y topes vive en `app/core/`, y
  `app/api/` solo traduce el resultado a `429` y cabeceras.

**Negativas / deuda aceptada:**

- **Se toleran hasta 60 peticiones en el borde de dos minutos consecutivos** (y 2 000 en el borde
  de dos días). Se acepta porque el techo de coste real es la cubeta diaria, y porque el gasto de
  esa ráfaga está acotado: a ~USD 0.009 por turno (RFC-0009 §4), 30 turnos extra son ~USD 0.27,
  una sola vez por borde y por clave.
- **`X-RateLimit-Remaining` es el de la cubeta más restringida en ese momento**, no un número por
  cada ventana. Publicar los dos exigiría cabeceras que el contrato no define.

**Condición de revisión:** se reabre si la PoC deja de tener un tope diario efectivo (por ejemplo,
si `RATE_LIMIT_PER_DAY` sube lo bastante como para que la ráfaga del borde deje de ser marginal
frente al presupuesto), o si aparece una clave compartida por varios consumidores —ahí la ráfaga
deja de ser un caso de borde y pasa a ser el patrón normal—. En cualquiera de los dos, la
alternativa a evaluar primero es el contador de ventana deslizante sobre dos cubetas, que no exige
migración.
