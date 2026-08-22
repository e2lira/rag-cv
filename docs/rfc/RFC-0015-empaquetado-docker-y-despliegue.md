# RFC-0015 — Empaquetado en contenedor y artefactos de despliegue

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aprobado |
| **Depende de** | RFC-0007, RFC-0008, RFC-0012, RFC-0013 |
| **Supersede** | RFC-0008 §5 (Dockerfile) |
| **Fecha** | 2026-08-22 |

---

## 1. Contexto y problema

El artefacto que se promueve entre entornos es una **imagen de contenedor**: se construye una
vez en el CI, se valida en QA y se despliega en PROD por digest (RNF-10). DEV es Windows nativo
y no la construye (RFC-0011), así que el `Dockerfile` no tiene ningún camino de validación local:
el CI es la primera y única red antes de QA.

Este RFC contiene el **contenido literal** de cada archivo de despliegue. Es normativo: el
Desarrollador lo transcribe, no lo reinterpreta. Cualquier desviación se declara en el Informe de
Implementación.

## 2. Alcance

**Entra:** `Dockerfile`, `.dockerignore`, `entrypoint.sh`, `docker-compose.qa.yml`,
`docker-compose.prod.yml`, `Caddyfile`, endurecimiento del contenedor, dimensionamiento, y la
semántica de los health checks.

**No entra:** el pipeline que construye y despliega (RFC-0008), la infraestructura de AWS
(RFC-0007), Terraform.

## 3. Principios del empaquetado

1. **Una imagen, cero ramas por entorno.** Lo que cambia entre QA y PROD es la configuración
   inyectada, nunca la imagen. Si el `Dockerfile` necesitara un `if` por entorno, el diseño está
   mal.
2. **Sin secretos en la imagen.** Ni en capas intermedias, ni en `ARG`, ni en el historial.
3. **Sin descargas en tiempo de ejecución.** Todo lo que la aplicación necesita está en la
   imagen. Al homologar embeddings sobre la Nomic API (RFC-0012) no hay pesos que empaquetar, así
   que esto sale gratis.
4. **Proceso no privilegiado, sistema de archivos de solo lectura.** Un contenedor que no puede
   escribir en su propio sistema de archivos no puede persistir un compromiso.
5. **Las migraciones no corren en el arranque.** Son un paso del despliegue (RFC-0006 §5). Con
   más de una réplica, dos procesos migrando a la vez es una carrera con daño real.

## 4. `Dockerfile`

```dockerfile
# syntax=docker/dockerfile:1.7

# ---------- etapa de construcción ----------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /build
RUN pip install --no-cache-dir uv==0.5.*

# Capa de dependencias: cambia solo si cambian los locks.
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project -o requirements.txt \
 && uv pip install --system --prefix=/install -r requirements.txt

# ---------- etapa de ejecución ----------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOME=/app

# libpq para psycopg; curl para el HEALTHCHECK. Nada más.
RUN apt-get update \
 && apt-get install --no-install-recommends -y libpq5 curl \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home ${APP_HOME} --shell /usr/sbin/nologin app

COPY --from=builder /install /usr/local

WORKDIR ${APP_HOME}

# Copia explícita. Nunca `COPY . .`: metería .env, .git, tests y notebooks.
COPY --chown=app:app app/         ./app/
COPY --chown=app:app migrations/  ./migrations/
COPY --chown=app:app corpus/      ./corpus/
COPY --chown=app:app alembic.ini  ./
COPY --chown=app:app entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Metadatos de trazabilidad: qué commit es esta imagen.
ARG GIT_SHA=unknown
ARG BUILD_DATE=unknown
ARG VERSION=0.0.0
LABEL org.opencontainers.image.title="rag-cv" \
      org.opencontainers.image.description="Agente de CV conversacional (API REST)" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="MIT"
ENV APP_VERSION=${VERSION} APP_GIT_SHA=${GIT_SHA}

USER app
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/healthz || exit 1

ENTRYPOINT ["./entrypoint.sh"]
CMD ["api"]
```

Decisiones y su motivo:

| Decisión | Motivo |
| :--- | :--- |
| Multi-etapa | La imagen final no lleva compiladores ni caché de `pip`: menos peso y menos superficie |
| `uv` con `uv.lock` | Reproducibilidad: sin *lock*, dos builds del mismo commit pueden diferir |
| Capa de dependencias separada de la del código | Un cambio de código no reinstala dependencias: el build baja de minutos a segundos |
| `COPY` explícito por directorio | `COPY . .` mete `.env`, `.git`, `tests/` y cualquier archivo suelto en la imagen |
| Usuario `app` con UID fijo 10001 | App Runner y cualquier auditoría de contenedores lo exigen; el UID fijo hace predecibles los permisos de volúmenes |
| `libpq5` sin `-dev` | El binario de `psycopg` necesita la biblioteca en ejecución, no las cabeceras |
| `HEALTHCHECK` sobre `/healthz`, no `/readyz` | `/healthz` responde si el proceso vive. `/readyz` toca la base de datos: usarlo aquí reiniciaría el contenedor cada vez que la BD tosa, convirtiendo una degradación en una caída |
| `ENTRYPOINT` + `CMD` separados | Permite `docker run rag-cv migrate` sin duplicar imágenes |
| `LABEL` con `revision` | Responder "¿qué código está corriendo en producción?" sin adivinar |

**Tamaño esperado:** ~180–220 MB. Si supera 300 MB, algo entró que no debía y es un hallazgo.

## 5. `.dockerignore`

Tan importante como el `Dockerfile`: es la segunda barrera contra meter un secreto en la imagen.

```gitignore
# Control de versiones y metadatos
.git
.gitignore
.gitattributes
.github

# Secretos y configuración local
.env
.env.*
!.env.example
*.pem
*.key

# Entornos y cachés de Python
.venv
venv
__pycache__
*.py[cod]
.mypy_cache
.ruff_cache
.pytest_cache
.coverage
htmlcov
*.egg-info

# Pruebas y evaluación (no van a la imagen de producción)
tests
evals
.mutmut-cache

# Documentación e infraestructura
docs
infra
scripts
*.md
!corpus/*.md

# Herramientas de desarrollo
.vscode
.idea
.atl
Thumbs.db
desktop.ini
```

`!corpus/*.md` es deliberado: el corpus **sí** entra en la imagen, porque la reindexación en PROD
lo lee desde el contenedor (RFC-0002 §8).

## 6. `entrypoint.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

# Los comandos son explícitos. No hay lógica condicional por entorno:
# lo que cambia entre QA y PROD es la configuración inyectada, no esto.
case "${1:-api}" in
  api)
    exec uvicorn app.main:app \
      --host 0.0.0.0 \
      --port "${PORT:-8080}" \
      --workers "${UVICORN_WORKERS:-2}" \
      --loop uvloop \
      --no-server-header \
      --proxy-headers \
      --forwarded-allow-ips '*'
    ;;
  migrate)
    exec alembic upgrade head
    ;;
  index)
    shift
    exec python -m app.ingestion.indexer --corpus "${CORPUS_PATH:-corpus/cv.md}" "$@"
    ;;
  shell)
    exec python
    ;;
  *)
    echo "Comando desconocido: $1 (api|migrate|index|shell)" >&2
    exit 64
    ;;
esac
```

Notas:

- **`exec`** en todas las ramas: el proceso de Python es el PID 1 y recibe `SIGTERM` directamente.
  Sin `exec`, el apagado ordenado no ocurre y las conexiones en curso se cortan de golpe.
- **`--no-server-header`**: no se anuncia la versión del servidor.
- **`--proxy-headers` con `--forwarded-allow-ips '*'`**: correcto **solo** porque el contenedor
  nunca está expuesto directamente (siempre detrás de Caddy o de App Runner). Si algún día se
  expusiera, este valor debe restringirse a la IP del proxy.
- **`--loop uvloop`**: en Linux siempre. Es la contrapartida de RFC-0011 §5.3, donde Windows usa
  el bucle `asyncio` con política Selector.
- **Este archivo debe estar en LF**, no CRLF: con CRLF muere con `bad interpreter: ^M`
  (RFC-0011 §5.4, `.gitattributes`).

## 7. Ejecución en QA — `infra/compose/docker-compose.qa.yml`

```yaml
name: rag-cv-qa

services:
  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      api: { condition: service_healthy }

  api:
    image: ghcr.io/${GITHUB_ORG}/rag-cv:${IMAGE_TAG}
    restart: unless-stopped
    env_file: [/opt/rag-cv/.env]
    environment:
      APP_ENV: qa
      DATABASE_URL: postgresql://ragcv:${POSTGRES_PASSWORD}@db:5432/ragcv
      UVICORN_WORKERS: "2"
    expose: ["8080"]                    # sin puerto publicado: solo la red interna
    depends_on:
      db: { condition: service_healthy }
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:8080/healthz"]
      interval: 30s
      timeout: 3s
      retries: 3
      start_period: 15s
    read_only: true
    tmpfs: ["/tmp:size=64m"]
    cap_drop: ["ALL"]
    security_opt: ["no-new-privileges:true"]
    logging:
      driver: json-file
      options: { max-size: "50m", max-file: "3" }

  db:
    image: pgvector/pgvector:pg16
    restart: unless-stopped
    environment:
      POSTGRES_USER: ragcv
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ragcv
      # Homologa la configuración regional con DEV y PROD (RFC-0006 §3.1).
      POSTGRES_INITDB_ARGS: "--encoding=UTF8 --locale-provider=icu --icu-locale=es-MX"
    volumes: ["pgdata:/var/lib/postgresql/data"]
    # Sin `ports`: la base de datos no es alcanzable desde fuera del host (RNF-7).
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ragcv -d ragcv"]
      interval: 5s
      timeout: 3s
      retries: 10
    logging:
      driver: json-file
      options: { max-size: "50m", max-file: "3" }

volumes:
  pgdata:
  caddy_data:
  caddy_config:
```

Cuatro cosas que no son opcionales:

- **`db` no publica puertos.** RNF-7 aplica también a QA: la base de datos solo existe dentro de
  la red del compose.
- **`read_only: true` + `tmpfs` + `cap_drop: ALL` + `no-new-privileges`.** La aplicación no
  necesita escribir en disco; quitarle la capacidad convierte una ejecución de código arbitrario
  en un problema mucho menor.
- **`POSTGRES_INITDB_ARGS` con ICU `es-MX`.** Sin esto, la búsqueda léxica en español se comporta
  distinto que en DEV y en PROD, sin dar ningún error (RFC-0006 §3.1).
- **Rotación de logs.** Un `json-file` sin límite llena el disco del VPS y tumba el servicio; es
  la avería más aburrida y más frecuente de un despliegue con compose.

### 7.1 `infra/compose/Caddyfile`

```caddyfile
qa.{$DOMINIO} {
    encode zstd gzip

    # SSE: sin buffering ni compresión que retenga los eventos.
    @stream path /v1/chat/stream
    handle @stream {
        reverse_proxy api:8080 {
            flush_interval -1
            transport http { versions 1.1 }
        }
    }

    handle {
        reverse_proxy api:8080
    }

    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "no-referrer"
        -Server
    }

    log {
        output file /data/access.log {
            roll_size 20mb
            roll_keep 5
        }
        format json
    }
}
```

`flush_interval -1` en la ruta de streaming es el detalle que hace que SSE funcione de verdad:
sin él, Caddy acumula los eventos y el usuario recibe la respuesta entera de golpe, lo que
destruye el objetivo de RNF-1 sin producir ningún error visible.

## 8. Producción con Docker — `infra/compose/docker-compose.prod.yml`

PROD en AWS usa **App Runner**, que consume directamente la imagen de ECR y no necesita compose
(RFC-0007 §6). Este archivo existe para el caso de desplegar la misma imagen en **cualquier host
con Docker** —un VPS, una máquina del cliente, una demostración— y es también el plan de
contingencia si App Runner no estuviera disponible.

```yaml
name: rag-cv-prod

services:
  api:
    image: ${IMAGE_REF}                 # siempre por digest: rag-cv@sha256:...
    restart: always
    env_file: [/opt/rag-cv/prod.env]
    environment:
      APP_ENV: prod
      UVICORN_WORKERS: "2"
    ports: ["127.0.0.1:8080:8080"]      # solo loopback; el TLS lo termina el proxy del host
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:8080/healthz"]
      interval: 30s
      timeout: 3s
      retries: 3
      start_period: 15s
    read_only: true
    tmpfs: ["/tmp:size=64m"]
    cap_drop: ["ALL"]
    security_opt: ["no-new-privileges:true"]
    deploy:
      resources:
        limits: { cpus: "1.0", memory: 1g }
        reservations: { memory: 512m }
    stop_grace_period: 30s              # margen para cerrar los SSE en curso
    logging:
      driver: json-file
      options: { max-size: "100m", max-file: "5" }
```

Diferencias deliberadas respecto a QA:

- **Imagen por digest, nunca por etiqueta móvil.** `:latest` en producción significa no saber qué
  está corriendo.
- **Sin servicio de base de datos.** En PROD la base es gestionada (RDS) o externa. Un Postgres
  en compose junto a la aplicación en producción mezcla el ciclo de vida de los datos con el del
  código.
- **`stop_grace_period: 30s`.** Una conversación en streaming puede durar decenas de segundos;
  el valor por defecto de 10 s las cortaría en cada despliegue.
- **Límites de recursos explícitos**, para que un fallo de la aplicación no se lleve por delante
  al resto del host.

### 8.1 Secuencia de despliegue

Idéntica en QA y en el PROD con Docker, y equivalente al pipeline de App Runner (RFC-0008 §7):

```bash
export IMAGE_REF=ghcr.io/<org>/rag-cv@sha256:<digest>
docker compose pull api
docker compose run --rm api migrate                       # migraciones: paso propio
docker compose up -d api
timeout 90 bash -c 'until curl -fsS http://127.0.0.1:8080/readyz; do sleep 3; done'
docker compose run --rm api index                         # reindexa el corpus
```

Las migraciones y la indexación son **comandos separados del arranque del servicio**: es lo que
permite que una migración fallida no deje el servicio en un bucle de reinicio.

## 9. Dimensionamiento

| Entorno | CPU / memoria | Workers | Justificación |
| :--- | :--- | :--- | :--- |
| QA (VPS) | 1 vCPU / 1 GB | 2 | Tráfico de evaluación, no de usuarios |
| PROD (App Runner) | 1 vCPU / 2 GB | 2 | Al homologar embeddings sobre la API de Nomic no hay modelo en memoria: la instancia pequeña basta (RFC-0012 §8) |
| PROD (Docker en host) | límite 1 vCPU / 1 GB | 2 | — |

**Concurrencia.** Con 2 workers y ~20 peticiones concurrentes por instancia, el cuello de botella
son las esperas de red (proveedor LLM y de embeddings), no la CPU: son esperas asíncronas, y por
eso 2 workers son suficientes. Subir workers sin subir CPU solo añade contención.

**Arranque en frío.** ~2 s. Se mantiene un mínimo de 1 instancia en App Runner: escalar a cero
ahorraría poco y rompería RNF-1 en la primera petición.

## 10. Endurecimiento — resumen verificable

| # | Medida | Dónde |
| :--- | :--- | :--- |
| 1 | Proceso no root (UID 10001) | `Dockerfile` |
| 2 | Sistema de archivos raíz de solo lectura | compose |
| 3 | Todas las capacidades eliminadas | compose |
| 4 | `no-new-privileges` | compose |
| 5 | Sin secretos en la imagen ni en sus capas | `.dockerignore` + revisión de `docker history` |
| 6 | Sin descargas en tiempo de ejecución | `Dockerfile` |
| 7 | Cabecera de servidor suprimida | `entrypoint.sh` |
| 8 | Base de datos sin puerto publicado | compose |
| 9 | Escaneo de la imagen (severidad ≥ HIGH bloquea) | CI, job 2 (RFC-0008) |
| 10 | SBOM generado y archivado por versión | CI, job 6 |

## 11. Criterios de aceptación

| # | Criterio | Verificación |
| :--- | :--- | :--- |
| CA-1 | La imagen pesa menos de 300 MB | `docker image inspect` en CI |
| CA-2 | El contenedor no corre como root | `docker run --rm <img> id` devuelve uid=10001 |
| CA-3 | La imagen no contiene `.env`, `.git`, `tests/` ni `docs/` | `docker run --rm <img> ls -a` + `docker history --no-trunc` |
| CA-4 | La imagen sí contiene `corpus/cv.md` | `docker run --rm <img> ls corpus/` |
| CA-5 | `docker run <img> migrate` aplica migraciones y sale con 0 | Job de humo del CI |
| CA-6 | `docker run <img>` arranca la API y `/healthz` responde 200 | Job de humo del CI |
| CA-7 | El `HEALTHCHECK` pasa a `healthy` en menos de 30 s | `docker inspect --format '{{.State.Health.Status}}'` |
| CA-8 | `SIGTERM` cierra el proceso ordenadamente en menos de 30 s | `docker stop` cronometrado, sin `SIGKILL` |
| CA-9 | Con `read_only: true` la aplicación funciona sin errores de escritura | Suite de humo contra el compose |
| CA-10 | El SSE llega token a token a través de Caddy | `curl -N` contra QA, midiendo el tiempo entre eventos |
| CA-11 | La base de datos de QA no es alcanzable desde fuera del host | `nc -z <host> 5432` desde otra máquina falla |
| CA-12 | Las etiquetas OCI llevan el `git sha` correcto | `docker inspect` comparado con el commit |
| CA-13 | `entrypoint.sh` está en LF | `file entrypoint.sh` en CI |
| CA-14 | El escaneo de vulnerabilidades no reporta severidad ≥ HIGH sin excepción firmada | Job 2 del CI |

## 12. Riesgos

| Riesgo | Mitigación |
| :--- | :--- |
| Un secreto acaba en una capa de la imagen | `.dockerignore` + `gitleaks` + revisión de `docker history` en el job de humo |
| El `Dockerfile` se rompe y no se detecta en DEV (sin Docker) | Jobs 6 y 6b tempranos y obligatorios (RFC-0008 §4.1) |
| CRLF en `entrypoint.sh` | `.gitattributes` + CA-13 |
| Caddy retiene los eventos SSE | `flush_interval -1` + CA-10 |
| Despliegue con etiqueta móvil en producción | El pipeline despliega **siempre** por digest (RFC-0008 §7) |
| Logs sin rotar llenan el disco del VPS | Límites `json-file` en todos los servicios |
| Migración en el arranque con varias réplicas | Comando separado (§8.1) + comprobación de auditoría |
| `read_only` rompe una biblioteca que escribe en disco | `tmpfs` en `/tmp` + CA-9 en el humo |

## Contrato de auditoría (gate ADU)

| # | Comprobación | Cómo se verifica | Severidad si falla |
| :--- | :--- | :--- | :--- |
| A-1 | El `Dockerfile` no tiene ramas por entorno | Lectura | Bloqueante |
| A-2 | El contenedor corre como usuario no privilegiado | CA-2 | Bloqueante |
| A-3 | No hay secretos en la imagen ni en su historial de capas | CA-3 + `docker history --no-trunc` | Bloqueante |
| A-4 | No hay `COPY . .`; las copias son explícitas por directorio | Lectura | Mayor |
| A-5 | Las migraciones no se ejecutan en el arranque del servicio | Lectura de `entrypoint.sh` y del `lifespan` | Bloqueante |
| A-6 | `exec` se usa en todas las ramas del entrypoint | Lectura + CA-8 | Mayor |
| A-7 | El compose de QA no publica el puerto de la base de datos | CA-11 | Bloqueante |
| A-8 | `read_only`, `cap_drop: ALL` y `no-new-privileges` están en ambos compose | Lectura | Mayor |
| A-9 | `POSTGRES_INITDB_ARGS` homologa la configuración regional con DEV y PROD | Lectura + prueba de `to_tsvector` (RFC-0006 CA-11) | Mayor |
| A-10 | El PROD con Docker referencia la imagen por digest, no por etiqueta | Lectura | Bloqueante |
| A-11 | Caddy no retiene los eventos SSE | CA-10 | Mayor |
| A-12 | Todos los servicios tienen rotación de logs configurada | Lectura | Menor |
| A-13 | El `.dockerignore` excluye `.env`, `.git`, `tests/`, `docs/` e incluye `corpus/` | CA-3, CA-4 | Mayor |
| A-14 | Las etiquetas OCI permiten identificar el commit desplegado | CA-12 | Menor |
