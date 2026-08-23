# RFC-0011 — Entorno de desarrollo nativo en Windows

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aprobado |
| **Depende de** | RFC-0007 (decisión de diseño, ya aprobada; no exige implementación previa) |
| **Fecha** | 2026-08-22 |

---

## 1. Contexto y problema

El desarrollo ocurre en **Windows con PostgreSQL, pgvector y Python instalados de forma
nativa**, sin Docker. QA corre en **Ubuntu** y PROD en **AWS (Linux)**. Es decir: la aplicación
se escribe en un sistema operativo y se ejecuta en otro en dos de los tres entornos.

Esto no es un problema si se declara y se contiene. Es un problema grave si se ignora, porque
produce la peor clase de fallo: código que funciona en la máquina de quien lo escribe y falla
al desplegar, o —peor— que funciona en ambos sitios pero con comportamiento distinto.

Este RFC define la instalación, las diferencias reales entre Windows y Linux que afectan a
**este** stack, cómo se neutraliza cada una, y qué queda sin validar en DEV (y dónde se valida
entonces).

## 2. Alcance

**Entra:** requisitos e instalación en Windows, creación de la base de datos con la
configuración regional correcta, incompatibilidades concretas de Python/psycopg/uvicorn en
Windows, scripts de tarea multiplataforma, estrategia de pruebas sin Docker, contrato de
paridad con Linux.

**No entra:** QA y PROD (RFC-0007), el pipeline (RFC-0008), el esquema (RFC-0006), la ingesta
(RFC-0002), la API de negocio (RFC-0005).

**Y sin embargo entra un `app/dev_server.py` mínimo.** El §7 exige probar que `uvicorn` arranca
en Windows sin el error de bucle de eventos (CA-4, CA-5), y eso no se puede verificar sin *algún*
punto de entrada `uvicorn` real. Este RFC construye el **esqueleto**: `app/core/platform.py`
—detección de plataforma y política de bucle de eventos— y `app/dev_server.py` con una única ruta
`/readyz` que responde `200` sin tocar base de datos ni lógica de negocio. Es la prueba de que el
mecanismo funciona, no la API. RFC-0005 lo amplía con el contrato real.

> **Ese esqueleto deja de arrancar sin base de datos (RFC-0021 §3.2).** `app/main.py` pasa a ser la
> aplicación real, cuyo `lifespan` valida la base y aborta si está mal (RFC-0006 §7); y
> `app/dev_server.py` no es una aplicación aparte, sino el **lanzador** que fija la política del
> bucle y arranca `app.main:app` — así que hereda esa validación.
>
> **CA-4 no se ve afectado:** `assert_compatible_loop()` es el paso 0 del `lifespan`, antes de
> cualquier conexión, así que el CLI de `uvicorn` sigue fallando por el bucle de eventos y no por
> la base (RFC-0021 §3.1, protegido por su A-2b).
>
> **CA-5 sí, y por eso se acotó**: deja de exigir «sin base de datos». Nació para probar el
> mecanismo del bucle cuando no había otra cosa que arrancar; hoy eso lo prueba CA-4 con un test
> unitario que no levanta ningún servidor. Y este RFC entero deja al desarrollador con la base
> `ragcv` ya creada: exigir que la aplicación arranque sin ella protegía un escenario que este
> mismo documento no contempla.

## 3. Requisitos de la estación de trabajo

| Componente | Versión | Cómo se instala |
| :--- | :--- | :--- |
| Windows | 10/11 x64 | — |
| PostgreSQL | **≥ 16.x** x64 (16.x recomendado, iguala el VPS de QA) | Instalador de EDB (incluye `unaccent` y `pg_trgm` en contrib) |
| pgvector | 0.8.5 o la que traiga el instalador de EDB | **Compilar con `nmake`** solo si el instalador no la incluye (§4.2) |
| Visual Studio Build Tools | 2022, carga «Desarrollo para el escritorio con C++» | Requisito **solo** para compilar pgvector |
| Python | 3.12 x64 | python.org o `winget install Python.Python.3.12` |
| Git | ≥ 2.40 | `winget install Git.Git` |

No se requiere Docker Desktop. Sus consecuencias están en §8.

## 4. Instalación

### 4.1 PostgreSQL

Instalación estándar del instalador de EDB. Después, en `postgresql.conf`:

```conf
listen_addresses = 'localhost'      # nunca la LAN, ni siquiera en DEV
shared_buffers = 256MB
max_connections = 50
```

El servicio queda registrado como `postgresql-x64-16`:

```powershell
Get-Service postgresql-x64-16
Restart-Service postgresql-x64-16
```

### 4.1.1 Sobre exigir exactamente PostgreSQL 16

Ninguno de los criterios de aceptación de §10 (CA-0 a CA-12) verifica un número de versión de
PostgreSQL. La comprobación exacta contra la versión real de producción **ya existe y corre en
Linux**: `TEST_DB_MODE=container` levanta `pgvector/pgvector:pg16` por *testcontainers* (§8), que
replica el 16.14 del VPS de QA. Es la autoridad — "Linux es la autoridad" (§9) — no este entorno.

**El requisito para DEV es un PostgreSQL con `vector` disponible, ≥ 16** (por la configuración
regional ICU de §4.3, que exige 16 o superior). Usar una versión mayor ya instalada en la máquina
—18, por ejemplo— es válido: RFC-0007 §3 asigna a DEV validar el código, no el artefacto, y esa
distinción es justo la que hace innecesaria la paridad exacta de versión aquí. Si algún día una
migración usara una característica exclusiva de una versión concreta, el job de CI contra
`pg16` lo detendría antes del merge, que es donde tiene que detenerse.

### 4.2 pgvector — compilación

pgvector **no publicaba binarios oficiales para Windows**, y el procedimiento de esta sección
sigue siendo la vía correcta si hace falta. **Verificalo primero**: los instaladores recientes de
EDB para Windows incluyen la extensión ya compilada — el paso 2 del bootstrap (§7) lo detecta y
solo cae a este procedimiento si `CREATE EXTENSION vector` falla. Desde el
*x64 Native Tools Command Prompt for VS 2022* **como administrador**:

```bat
set "PGROOT=C:\Program Files\PostgreSQL\16"
cd %TEMP%
git clone --branch v0.8.5 https://github.com/pgvector/pgvector.git
cd pgvector
nmake /F Makefile.win
nmake /F Makefile.win install
```

Esto deja `vector.dll` en `%PGROOT%\lib` y los `.sql`/`.control` en
`%PGROOT%\share\extension`. Verificación:

```sql
SELECT * FROM pg_available_extensions WHERE name = 'vector';
```

Fallos habituales y su causa:

| Síntoma | Causa | Solución |
| :--- | :--- | :--- |
| `Cannot open include file: 'postgres.h'` | `PGROOT` mal apuntado o falta el paquete de desarrollo | Comprobar que existe `%PGROOT%\include\server\postgres.h` |
| `unresolved external symbol` | Se usó el prompt x86 en vez del x64 | Usar *x64 Native Tools* |
| `nmake` no reconocido | No se abrió el prompt de VS | Abrirlo desde el menú Inicio, no `cmd` |
| Falla al instalar la DLL | Prompt sin privilegios | Ejecutar como administrador |

**Esta compilación se repite en cada actualización mayor de PostgreSQL.** Queda anotada en el
runbook (RFC-0010) porque es un paso manual fácil de olvidar que rompe el arranque con un error
poco descriptivo.

### 4.3 Creación de la base de datos

La configuración regional del clúster de Windows es la fuente de un fallo silencioso: si la
clasificación de caracteres no reconoce los acentuados como letras, `to_tsvector` los trocea mal
y la rama léxica de RFC-0003 deja de encontrar "informática", **sin dar ningún error**.

```sql
CREATE DATABASE ragcv
  WITH ENCODING 'UTF8'
       LOCALE_PROVIDER = 'icu'
       ICU_LOCALE = 'es-MX'
       TEMPLATE = template0;

\c ragcv
CREATE EXTENSION vector;
CREATE EXTENSION unaccent;
CREATE EXTENSION pg_trgm;
```

**La verificación de abajo usa `es_unaccent`, y esa configuración no la crea ninguna de las tres
extensiones anteriores.** Vive en la migración inicial de Alembic
(`migrations/versions/0001_rfc0006_initial_schema.py`), que es artefacto de
RFC-0006 (fuera del alcance de este RFC, §2). Sin este bloque, las consultas de verificación
fallan con `text search configuration "es_unaccent" does not exist` — un error que no dice nada
sobre el problema real (la configuración regional), y por eso hay que evitarlo aquí:

```sql
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_ts_config AS config
        JOIN pg_namespace AS namespace ON namespace.oid = config.cfgnamespace
        WHERE namespace.nspname = 'public'
          AND config.cfgname = 'es_unaccent'
    ) THEN
        CREATE TEXT SEARCH CONFIGURATION public.es_unaccent (COPY = spanish);
    END IF;
END;
$$;

ALTER TEXT SEARCH CONFIGURATION public.es_unaccent
    ALTER MAPPING FOR hword, hword_part, word WITH unaccent, spanish_stem;
```

**Es el mismo texto, palabra por palabra, que usa la migración inicial de RFC-0006.** No es
una duplicación accidental: es deliberada, para que cuando RFC-0006 lo vuelva a aplicar sea un
no-op idempotente (`IF NOT EXISTS`), no una segunda fuente de verdad que pueda divergir. Si algún
día cambia la definición de `es_unaccent`, cambia en los dos sitios a la vez o queda documentada
la deriva.

Se usa el proveedor **ICU** (disponible desde PostgreSQL 16) en lugar de la configuración
regional de Windows, porque `Spanish_Mexico.1252` no es compatible con `UTF8` y `C` clasifica
mal los acentos. ICU da el mismo comportamiento que el `es_MX.UTF-8` de Ubuntu, que es
exactamente lo que se busca.

**La verificación no es opcional.** El invariante se prueba, no se asume, y la misma prueba
corre en Windows y en Linux:

```sql
-- debe devolver los lexemas sin acento: 'informat':1 'ingenier':2
SELECT to_tsvector('es_unaccent', 'Informática Ingeniería');
-- debe devolver true
SELECT to_tsvector('es_unaccent','informática') @@ websearch_to_tsquery('es_unaccent','informatica');
```

### 4.4 Entorno de Python

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip uv
uv sync                      # instala desde uv.lock, incluidas las de desarrollo
```

`psycopg[binary,pool]` distribuye *wheels* para Windows: no hace falta compilar nada más.

### 4.5 Variables de entorno de DEV (`.env`)

> **Este bloque estaba escrito para el diseño con AWS (Bedrock, Titan) y quedó desactualizado
> tras ADR-0006/ADR-0007/ADR-0008.** RFC-0016 §7 es la fuente de la configuración vigente; lo que
> sigue es su traducción literal a `.env` de DEV, sin abrir un segundo documento.

```dotenv
APP_ENV=dev
LOG_LEVEL=DEBUG
DATABASE_URL=postgresql://postgres:<password>@localhost:5432/ragcv

# Generación: API de Anthropic, no Bedrock (ADR-0008, RFC-0018)
PROVEEDOR=anthropic
ANTHROPIC_MODEL_ID=claude-haiku-4-5
ANTHROPIC_API_KEY=<clave>

# Embeddings: API de OpenAI, no Titan (ADR-0007, RFC-0017)
EMBEDDER=openai
OPENAI_EMBED_MODEL=text-embedding-3-small
OPENAI_API_KEY=<clave>
EMBEDDING_DIM=1536

CORPUS_PATH=corpus/cv.md
PYTHONUTF8=1
```

**Sin ninguna variable `AWS_*`, y a propósito** (RFC-0016 §7): la aplicación no depende de AWS.
Las dos credenciales del entorno son `ANTHROPIC_API_KEY` y `OPENAI_API_KEY`. No hay paso de consola
de Bedrock que habilitar.

**Sobre Ollama en el equipo.** Está instalado y sirve `nomic-embed-text`, pero **no es el camino
por defecto** (ADR-0004). Queda como contingencia para trabajar sin red:

```dotenv
EMBEDDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
EMBEDDING_DIM=768
```

Activarlo cambia la **dimensión** (1024 → 768) y el `embed_model_id`, así que exige recrear la
columna y reindexar la base local (RFC-0012 §7.1); el arranque lo detecta y aborta si no se hace.
Y hay una trampa al probar a mano: `ollama.embeddings(model="nomic-embed-text", prompt=texto)`
**no añade los prefijos de tarea**; hay que anteponer `search_document: ` o `search_query: `
(RFC-0012 §3). La implementación `OllamaEmbedder` lo hace por su cuenta; una prueba manual en la
consola, no.

`.env` está en `.gitignore`. En Windows no existe `chmod 600`: se restringe con ACL.

```powershell
icacls .env /inheritance:r /grant:r "$env:USERNAME:(R,W)"
```

El código **nunca** comprueba modos de archivo POSIX: fallaría en Windows y daría falsa
seguridad. La protección del secreto local es responsabilidad del sistema de archivos.

## 5. Incompatibilidades de Windows que afectan a este stack

Cada una está resuelta en el código, no en la cabeza de quien desarrolla.

### 5.1 psycopg 3 asíncrono no funciona con el *event loop* por defecto

Python en Windows usa `ProactorEventLoop` por defecto. psycopg lo rechaza en modo asíncrono:

```text
psycopg.errors.InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run in async mode.
Please use a compatible event loop, for instance by setting
'asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())'
```

**Solución.** `app/core/platform.py`, importado como primera línea de `app/main.py`:

```python
import asyncio
import sys

def configure_event_loop() -> None:
    """En Windows, psycopg async exige SelectorEventLoop. Debe ejecutarse
    ANTES de que se cree cualquier bucle de eventos."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

def assert_compatible_loop() -> None:
    """Comprobación de arranque: falla claro en vez de fallar en la primera consulta."""
    if sys.platform == "win32":
        loop = asyncio.get_running_loop()
        if type(loop).__name__ == "ProactorEventLoop":
            raise RuntimeError(
                "Bucle de eventos incompatible con psycopg async. "
                "Arranca con 'python -m app.dev_server', no con el CLI de uvicorn."
            )
```

`assert_compatible_loop()` se llama en el `lifespan` de FastAPI. Sin esta comprobación, el
síntoma sería un error de conexión a la base de datos en la primera petición, que lleva a
investigar la base de datos durante media hora en lugar del bucle de eventos.

### 5.2 El CLI de `uvicorn` no garantiza la política del bucle

Establecer la política antes de invocar el CLI no siempre surte efecto: el CLI crea su propio
bucle. En DEV se arranca con un lanzador propio:

```python
# app/dev_server.py
from app.core.platform import configure_event_loop

configure_event_loop()          # antes de importar/arrancar uvicorn

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8080,
        reload=True,
        loop="asyncio",         # nunca uvloop; no existe en Windows
        workers=1,              # reload y workers son incompatibles
    )
```

```powershell
python -m app.dev_server
```

En QA y PROD se sigue usando el CLI de uvicorn del `Dockerfile`: en Linux no aplica nada de
esto.

### 5.3 `uvloop` no existe en Windows

La dependencia se declara con marcador de plataforma, de modo que Linux la use y Windows ni la
intente instalar:

```toml
dependencies = [
  "uvloop>=0.19; sys_platform != 'win32'",
]
```

Consecuencia declarada: **DEV y PROD usan bucles de eventos distintos.** No cambia la semántica
del código asíncrono, pero sí el rendimiento; ninguna medición de latencia hecha en Windows es
comparable con PROD. Las cifras de RNF-1/RNF-2 se miden en QA y en PROD, nunca en DEV.

### 5.4 Finales de línea

Los archivos del repositorio ya presentan la mezcla habitual (CRLF en disco, LF en los objetos
de Git), que produce diffs de archivo completo. Se corrige de una vez con `.gitattributes`:

```gitattributes
* text=auto eol=lf
*.ps1   text eol=crlf
*.bat   text eol=crlf
*.cmd   text eol=crlf
*.sh    text eol=lf
Dockerfile      text eol=lf
*.md    text eol=lf
*.py    text eol=lf
*.sql   text eol=lf
*.png binary
*.pdf binary
```

Y una vez, tras añadirlo:

```powershell
git add --renormalize .
git commit -m "chore: normalizar finales de línea [RFC-0011]"
```

Un script `.sh` con CRLF que llegue al VPS falla con `bad interpreter: /bin/bash^M`. Por eso
`*.sh` y `Dockerfile` se fijan a LF de forma explícita, no por `text=auto`.

### 5.5 Sistema de archivos sin distinción de mayúsculas

NTFS no distingue mayúsculas: `from app.Core import config` funciona en Windows y falla en
Ubuntu. Mitigaciones: todos los módulos y paquetes en minúsculas con guion bajo, y **el CI en
Linux es la autoridad** — un PR que solo pasa en Windows no se fusiona (RFC-0008).

### 5.6 Rutas y codificación

- Todas las rutas se construyen con `pathlib.Path`; ninguna cadena literal con `/` o `\`.
- La raíz del proyecto se resuelve desde el módulo (`Path(__file__).resolve().parents[2]`), no
  desde el directorio de trabajo, que en Windows cambia según cómo se lance el proceso.
- `PYTHONUTF8=1` en el `.env` y en la configuración del intérprete: la consola de Windows usa
  cp1252 por defecto y los logs JSON con acentos salen corruptos o lanzan
  `UnicodeEncodeError`.
- Ningún `os.path.join` con separadores fijos, ningún `open()` sin `encoding="utf-8"`.

### 5.7 Antivirus

Windows Defender analiza en tiempo real el directorio de datos de PostgreSQL y `.venv`, lo que
puede multiplicar por varios los tiempos de prueba. Se recomienda excluir
`C:\Program Files\PostgreSQL\16\data` y la carpeta `.venv` del proyecto. Es una recomendación
de comodidad, no un requisito.

## 6. Tareas multiplataforma

Windows no tiene `make`, y mantener `Makefile` + `.ps1` en paralelo garantiza que uno de los dos
se quede obsoleto. Se usa **un único `tasks.py`** con `invoke` (Python puro, mismo comando en
Windows, Ubuntu y en el CI):

```python
# tasks.py
from invoke import task

@task
def db_up(c):       c.run("alembic upgrade head")
@task
def index(c, force=False):
    c.run(f"python -m app.ingestion.indexer --corpus corpus/cv.md {'--force' if force else ''}")
@task
def dev(c):         c.run("python -m app.dev_server")
@task
def lint(c):
    c.run("ruff check ."); c.run("ruff format --check ."); c.run("mypy app/"); c.run("lint-imports")
@task
def test(c, kind="unit"):  c.run(f"pytest -m {kind}")
@task
def evals(c, suite="pr"):  c.run(f"python evals/run_eval.py --suite {suite}")
```

```powershell
invoke lint ; invoke test ; invoke dev
```

Solo hay dos scripts de shell en el repositorio, y ninguno se ejecuta en Windows:
`infra/vps/bootstrap.sh` (aprovisionamiento del VPS) y el script de despliegue de QA.

## 7. Bootstrap del entorno

`scripts/bootstrap-dev.ps1`, idempotente, ejecutable las veces que haga falta:

```powershell
# 1. Verifica versiones (Python 3.12, PostgreSQL >= 16, git)
# 2. Verifica que la extensión vector esté disponible; si no, imprime las
#    instrucciones de compilación de §4.2 y sale con código 1
# 3. Crea la base de datos 'ragcv' con ICU es-MX si no existe (idempotente)
# 4. Crea las extensiones vector, unaccent, pg_trgm
# 5. Ejecuta la prueba de configuración de texto de §4.3 y falla si no pasa
# 6. Crea el venv, instala dependencias con uv sync
# 7. Copia .env.example a .env si no existe y aplica la ACL
# 8. Si existe alembic.ini: alembic upgrade head. Si no (RFC-0006 aun no
#    implementado), lo omite con un aviso -- no es un fallo del bootstrap.
# 9. Si existe app/ingestion/indexer.py: reindexa. Si no (RFC-0002 aun no
#    implementado), lo omite con un aviso.
# 10. Imprime el resumen y el comando para arrancar
```

El paso 5 es el que evita el fallo silencioso de §4.3: el entorno no se declara listo si la
búsqueda léxica en español no se comporta como en Linux.

**Por qué los pasos 8 y 9 son condicionales, y no un error de este documento.** El §2 excluye
explícitamente el esquema (RFC-0006) y la ingesta (RFC-0002) del alcance de este RFC. Si el
bootstrap exigiera esos pasos sin condición, este RFC sería literalmente imposible de implementar
en aislamiento — contradiría su propio Definition of Ready (ADU-PROCESO §4, punto 6:
"Dependencias — RFCs previos que deben estar Implementado"), porque ninguno de los dos está
implementado todavía. La condicionalidad es lo que permite que **este RFC sea el primero de la
cadena** sin mentir sobre lo que hace: en su primera ejecución dice "no hay migraciones ni corpus
que indexar todavía" y se detiene ahí; cuando RFC-0006 y RFC-0002 aterricen, los mismos pasos
empiezan a ejecutarse sin tocar el script.

## 8. Estrategia de pruebas sin Docker

RFC-0003 y RFC-0006 especifican pruebas de integración con `testcontainers`, que necesita
Docker. En DEV no lo hay. Solución: **un mismo conjunto de pruebas, dos formas de obtener la
base de datos**, seleccionadas por variable de entorno.

| Modo | Dónde | Cómo obtiene la base de datos |
| :--- | :--- | :--- |
| `TEST_DB_MODE=local` (por defecto en Windows) | DEV | Crea `ragcv_test_<pid>` en el PostgreSQL nativo con la misma plantilla e ICU, ejecuta las migraciones y la elimina al terminar |
| `TEST_DB_MODE=container` (por defecto en CI/Linux) | CI, QA | `testcontainers` con `pgvector/pgvector:pg16` |

```python
# tests/conftest.py (esquema)
@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    mode = os.getenv("TEST_DB_MODE", "container" if sys.platform != "win32" else "local")
    if mode == "local":
        yield from _ephemeral_local_database()   # CREATE DATABASE ... / DROP DATABASE
    else:
        yield from _testcontainer_database()
```

Las pruebas **no cambian**: reciben `database_url` y punto. Lo que cambia es de dónde sale.
Esto mantiene una sola suite y evita el escenario clásico de "las pruebas de integración solo
las corre el CI y nadie las mira".

La base de prueba se crea con la misma sentencia `CREATE DATABASE` de §4.3: si la configuración
regional difiere entre la base de desarrollo y la de prueba, las pruebas de búsqueda léxica
mienten.

## 9. Qué NO se valida en DEV

Declararlo es el punto entero de este RFC.

| No se valida en DEV | Riesgo | Dónde se valida |
| :--- | :--- | :--- |
| Nada relativo a embeddings o generación: DEV usa **los mismos proveedores** que QA y PROD | — | Homologado a propósito (ADR-0004, ADR-0005) |
| La imagen de contenedor (no hay Docker) | Un `Dockerfile` roto solo se ve al abrir PR | Job 6 del CI (RFC-0008) + humo del contenedor |
| Comportamiento con `uvloop` | Diferencias de rendimiento y de temporización asíncrona | QA y PROD |
| Rutas y nombres sensibles a mayúsculas | Import que falla solo en Linux | Jobs de CI en `ubuntu-latest` |
| Permisos POSIX y usuario no-root del contenedor | Fallo de permisos solo en ejecución real | CI (job 6) y despliegue a QA |
| Latencia real (RNF-1/RNF-2/RNF-3) | Cifras de Windows no son comparables | Medición en QA y PROD (RFC-0010) |
| Scripts `.sh` y despliegue por SSH | CRLF, permisos de ejecución | CI + despliegue a QA |
| Comportamiento de RDS (límites de conexión, parámetros) | Divergencia con el Postgres local | QA (parcial) y PROD |
| Rol IAM de instancia | La cadena de credenciales difiere | QA usa usuario IAM, PROD rol; ambas por la cadena por defecto de boto3 |

**Regla derivada:** ningún PR se fusiona con el argumento "en mi máquina funciona". El CI en
Linux es la autoridad sobre lo que funciona (RFC-0008 §4, y por eso se añade un job de pruebas
unitarias en `windows-latest`: para proteger también el camino inverso).

## 10. Criterios de aceptación

| # | Criterio | Verificación |
| :--- | :--- | :--- |
| CA-0' | El bootstrap comprueba que existe `OPENAI_API_KEY` y no declara el entorno listo si falta. *(Sustituye al CA-0 original —acceso a Bedrock— derogado por ADR-0006: RFC-0016 §3.1)* | Ejecutar sin la variable definida |
| CA-1 | `scripts/bootstrap-dev.ps1` completa los pasos 1-7 y 10 desde cero, es idempotente, y los pasos 8-9 se omiten con aviso si sus RFCs no están implementados todavía | Ejecutarlo dos veces en una máquina limpia, sin `alembic.ini` ni `app/ingestion/` presentes |
| CA-2 | El bootstrap falla con instrucciones claras si `vector` no está disponible | Ejecutar sin pgvector instalado |
| CA-3 | La prueba de configuración de texto (§4.3) pasa en Windows y en Ubuntu con el mismo resultado | `pytest tests/integration/test_text_search.py` en ambos |
| CA-4 | Arrancar `app.dev_server` con el CLI de uvicorn en Windows produce un error claro sobre el bucle de eventos, no un error de base de datos | `pytest tests/unit/test_platform.py::test_proactor_detected` |
| CA-5 | `python -m app.dev_server` arranca y `/readyz` responde 200 en Windows | Manual + humo |
| CA-6 | `uvloop` no se instala en Windows y sí en Linux | `uv sync` en ambos + inspección |
| CA-7 | Existe `.gitattributes` y `git status` está limpio tras `--renormalize` | `git status --short` vacío |
| CA-8 | Ningún `.sh` ni el `Dockerfile` tienen CRLF | `file infra/**/*.sh Dockerfile` en el CI |
| CA-9 | `pytest -m integration` pasa en Windows con `TEST_DB_MODE=local` | Ejecución local |
| CA-10 | La base de prueba efímera se elimina siempre, también si la suite falla | Ejecutar con fallo forzado y comprobar `\l` |
| CA-11 | No hay rutas literales con separadores ni `open()` sin `encoding` | `ruff` con reglas `PTH` y `UP` + revisión |
| CA-12 | `invoke lint test` funciona igual en Windows y en Ubuntu | Ejecución en ambos + job de CI |

## 11. Riesgos

| Riesgo | Mitigación |
| :--- | :--- |
| pgvector deja de compilar tras actualizar PostgreSQL | Paso documentado en el runbook; el bootstrap lo detecta y da las instrucciones |
| Configuración regional distinta entre DEV y QA sin que nadie lo note | CA-3 corre en ambos sistemas y es gate de CI |
| Código que solo funciona en Windows | CI en `ubuntu-latest` como autoridad + job en `windows-latest` para el camino inverso |
| Medir latencia en Windows y sacar conclusiones | Documentado en §5.3 y §9; las cifras de RNF se miden en QA/PROD |
| El `Dockerfile` se rompe sin que se note en DEV | Job de build temprano en CI y humo del contenedor |
| Deriva entre `tasks.py` y los comandos reales del CI | El CI invoca `invoke ...`, no comandos duplicados |

## Contrato de auditoría (gate ADU)

| # | Comprobación | Cómo se verifica | Severidad si falla |
| :--- | :--- | :--- | :--- |
| A-1 | Existe `app/core/platform.py` con la política de bucle y la comprobación de arranque | Lectura + CA-4 | Bloqueante |
| A-2 | `uvloop` está declarado con marcador `sys_platform != 'win32'` | Lectura de `pyproject.toml` | Mayor |
| A-3 | Existe `.gitattributes` con `*.sh` y `Dockerfile` fijados a LF | CA-7, CA-8 | Mayor |
| A-4 | La suite de integración funciona en los dos modos (`local` y `container`) | CA-9 + ejecución en CI | Bloqueante |
| A-5 | La base de datos de prueba se crea con la misma configuración regional que la de desarrollo | Lectura del `conftest` | Mayor |
| A-6 | La base de prueba efímera se elimina siempre | CA-10 | Mayor |
| A-7 | No hay `Makefile` ni scripts duplicados por sistema operativo; el CI usa `invoke` | Inspección del repositorio y de los workflows | Menor |
| A-8 | El código no comprueba modos de archivo POSIX ni usa separadores literales | CA-11 | Mayor |
| A-9 | El CI incluye un job de unitarias en `windows-latest` | Lectura del workflow | Mayor |
| A-10 | La tabla de §9 refleja lo realmente no validado en DEV | Comparación con el pipeline | Menor |
| A-11 | El bootstrap verifica la configuración de texto antes de declarar el entorno listo | CA-2, CA-3 | Mayor |
