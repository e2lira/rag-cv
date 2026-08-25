# ADR-0019 — La configuración regional de ICU no vive en `datcollate`

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aceptada |
| **Fecha** | 2026-08-25 |
| **Decide** | Arquitecto |
| **RFCs afectados** | RFC-0020 (CA-16) |
| **Severidad del defecto que corrige** | Bloqueante — el criterio ordenaba destruir una base correcta |

## Contexto

RFC-0020 CA-16 prescribía esta verificación:

> `SELECT datlocprovider, datcollate FROM pg_database WHERE datname='ragcv'` devuelve `i` y `es-MX`

**Esa condición no puede cumplirse nunca.** En una base creada como manda RFC-0006 §3.1
—`LOCALE_PROVIDER = 'icu' ICU_LOCALE = 'es-MX' TEMPLATE = template0`— `datcollate` no contiene la
configuración regional de ICU: contiene la de `libc`, heredada del servidor.

Medido sobre una base creada correctamente:

```
datlocprovider = 'i'
datcollate     = 'Spanish_Mexico.1252'   <- lo que CA-16 mandaba mirar
datlocale      = 'es-MX'                 <- donde vive de verdad
```

Y sobre el VPS de QA, PostgreSQL 16, con la misma base bien creada: `datlocprovider = i`,
`datcollate = en_US.UTF-8`. El valor de `datcollate` es simplemente el del servidor, y varía por
host: `Spanish_Mexico.1252` en un Windows, `en_US.UTF-8` en el VPS. **No dice nada sobre ICU.**

### Por qué esto es Bloqueante y no Menor

Un criterio que no verifica lo que dice verificar es malo. Este es peor: **al no cumplirse jamás,
ordena una acción destructiva sobre un sistema correcto.**

El Desarrollador implementó CA-16 al pie de la letra. El aprovisionamiento comparaba contra
`i es-MX`, no coincidía, y emitía:

```
!! la base NO tiene ICU es-MX. Hay que RECREARLA ahora que esta vacia:
     sudo -u postgres dropdb ragcv
```

Sobre una base **correctamente creada con ICU `es-MX`**. La verificación de CA-16 existe
precisamente porque el paso es irreversible; el criterio mal escrito convirtió esa salvaguarda en
la instrucción de borrar. Se detuvo antes de ejecutarse porque el operador reportó el valor
observado y se comprobó contra un PostgreSQL real antes de actuar.

### El agravante: el nombre de la columna cambia entre versiones

| Versión | Columna |
| :--- | :--- |
| PostgreSQL ≤ 14 | No existe (no hay proveedor ICU por base) |
| PostgreSQL 15–16 | `daticulocale` |
| PostgreSQL ≥ 17 | `datlocale` |

El VPS de QA corre PostgreSQL 16; la máquina de desarrollo, 18. Una verificación escrita contra un
nombre fijo falla al actualizar el servidor —o al ejecutarse en la otra máquina— con un
`UndefinedColumn` que parece un problema de permisos o de conexión.

## Decisión

**CA-16 se verifica sobre `datlocprovider` y sobre la columna de locale de ICU que corresponda a la
versión del servidor, nunca sobre `datcollate`.**

- `datlocprovider` debe ser `i`.
- La configuración regional de ICU se lee de `daticulocale` en PostgreSQL 15–16 y de `datlocale` en
  PostgreSQL ≥ 17, y debe ser `es-MX`.
- `datcollate` **no se compara con nada**. Su valor es legítimo que difiera entre hosts.

La implementación debe resolver el nombre de la columna a partir de la versión del servidor, no
asumir una. Cómo hacerlo es del Desarrollador; qué tiene que ser cierto, de este ADR.

### Lo que NO cambia

La forma de **crear** la base era correcta y sigue igual: `LOCALE_PROVIDER = 'icu'
ICU_LOCALE = 'es-MX' TEMPLATE = template0` (RFC-0006 §3.1). El defecto estaba solo en cómo se
comprobaba lo ya creado. `app/core/db_bootstrap.py` no leía `datcollate` y no requiere cambios.

Tampoco cambia la segunda mitad de CA-16 —la consulta de RFC-0006 §3.1 ejecutada contra el VPS—,
que es la que comprueba el efecto observable: que la búsqueda léxica encuentre un término acentuado
escrito sin tilde. Esa mitad estaba bien y es, de hecho, la más importante: verifica la propiedad
que importa, no la configuración que se supone que la produce.

## Consecuencias

- **RFC-0020 CA-16 queda enmendado.** No se renumera ni se recicla nada: la fila gana la corrección.
- **`deploy/provision.sh` debe corregirse** antes de volver a ejecutarse en el VPS. Hasta entonces,
  su paso 2b rechaza bases correctas.
- **La base de QA no debe recrearse.** El valor observado (`i` + `en_US.UTF-8` en `datcollate`) es
  el de una base bien creada; hay que confirmar `daticulocale = 'es-MX'` y seguir.
- La prueba de integración que RFC-0020 ganó en la PR #99 —que ejecuta el SQL del aprovisionamiento
  contra un PostgreSQL real— es la que hace verificable esta corrección. Sin ella, el nombre de
  columna equivocado vuelve a descubrirse en el VPS.

## Una lección de método, porque es la tercera vez

Este ADR nace del mismo patrón que ADR-0017 y que los hallazgos de A-17 y A-18: **un criterio
escrito sin ejecutarse contra el sistema real.** CA-16 parecía razonable leyéndolo, y era imposible
de cumplir.

La regla que se deriva, y que conviene tener presente al escribir criterios: **un criterio de
aceptación que prescribe una consulta concreta debe haberse ejecutado al menos una vez contra el
motor real antes de fijarse en un RFC.** Prescribir SQL sin ejecutarlo es prescribir una suposición
con formato de hecho — y el Desarrollador la implementará al pie de la letra, porque eso es
exactamente lo que el proceso le pide.
