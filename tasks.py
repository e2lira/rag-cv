"""Tareas multiplataforma, un unico comando en Windows, Ubuntu y en el CI.

Contrato normativo: docs/rfc/RFC-0011-entorno-dev-windows-nativo.md #6.
Windows no tiene `make`; mantener Makefile + .ps1 en paralelo garantiza que
uno de los dos se quede obsoleto.

db_up, index y evals apuntan a modulos de RFCs que todavia no existen
(RFC-0006, RFC-0002, RFC-0009): fallan si se invocan hoy, y eso es
esperado, no un error de este archivo.

Desviacion declarada respecto al contrato literal de #6: `lint` no incluye
todavia `lint-imports`. Import-linter necesita un contrato de capas
(Domain/Application/Adapters, RFC-0001) que aun no existe; agregarlo sin
configuracion real rompe `invoke lint` siempre, no solo cuando falta el
RFC que lo habilita -- y CA-12 exige que `invoke lint test` funcione hoy.
Se agrega cuando RFC-0001 defina los limites reales que hay que hacer
cumplir.
"""

import ast
from pathlib import Path

from invoke import task


@task
def db_up(c):
    c.run("alembic upgrade head")


@task
def index(c, force=False):
    c.run(f"python -m app.ingestion.indexer --corpus corpus/cv.md {'--force' if force else ''}")


@task
def dev(c):
    c.run("python -m app.dev_server")


_PY_PATHS = "app/ tests/ scripts/ tasks.py migrations/"


# Prohibiciones del gate ADU que se comprueban sobre el ARBOL, no sobre el
# comportamiento. Viven aqui y no en una prueba por dos razones: el contrato
# de auditoria las prescribe como `grep` (RFC-0005, A-17 y A-18), y RFC-0014
# #5 exige que una prueba `unit` no haga IO -- recorrer el repositorio lo es.
# `lint` ya lee el arbol entero con ruff y mypy, asi que es su sitio.
#
# Los prefijos se componen por concatenacion a proposito: si estuvieran
# escritos enteros, este archivo se delataria a si mismo y habria que
# excluirlo -- y una prohibicion con excepciones deja de ser auditable con un
# `grep`, que es justo lo que la hace verificable.
_PREFIJOS_PROHIBIDOS: dict[str, tuple[str, str]] = {
    # A-17: ninguna prueba trae una clave de produccion ni de proveedor
    # (RFC-0005 #14). Sin excepcion, tampoco para un caso negativo: quien
    # audita no puede distinguir de un vistazo el fixture del descuido.
    "rcv" + "_live_": ("tests", "clave de produccion (RFC-0005 6.1)"),
    "sk-" + "ant-api": ("tests", "clave de Anthropic"),
    "sk-" + "proj-": ("tests", "clave de OpenAI"),
    "AKIA" + "IOSFODNN": ("tests", "credencial de AWS"),
    # A-18: `app/` no resuelve secretos contra AWS. El gate exige CERO
    # coincidencias, tambien en comentarios: un `grep` no distingue prosa de
    # codigo, y esa indiferencia es lo que lo hace auditable sin criterio.
    "secretsmanager": ("app", "cliente de Secrets Manager"),
    "boto" + "3": ("app", "SDK de AWS"),
    "API_KEYS_" + "SECRET_ID": ("app", "secreto remoto de claves"),
}

# La unica lectura de entorno permitida (RFC-0001 #4).
_LECTOR_DE_ENTORNO = Path("app/core/settings.py")
_LECTURAS_DE_ENTORNO = {"environ", "getenv"}


def _infractores_por_prefijo() -> list[str]:
    aqui = Path(__file__).resolve()
    hallazgos = []
    for prefijo, (carpeta, motivo) in _PREFIJOS_PROHIBIDOS.items():
        for archivo in sorted(Path(carpeta).rglob("*.py")):
            if archivo.resolve() == aqui:
                continue
            lineas = archivo.read_text(encoding="utf-8").splitlines()
            hallazgos += [
                f"{archivo}:{numero} -- {motivo}"
                for numero, linea in enumerate(lineas, start=1)
                if prefijo in linea
            ]
    return hallazgos


def _lecturas_de_entorno_fuera_de_settings() -> list[str]:
    """RFC-0001 #4: la capa de configuracion es la unica que lee el entorno.

    Sobre el AST y no con `grep`, para no marcar la palabra `environ` dentro
    de una cadena o de un comentario."""
    hallazgos = []
    for archivo in sorted(Path("app").rglob("*.py")):
        if archivo == _LECTOR_DE_ENTORNO:
            continue
        arbol = ast.parse(archivo.read_text(encoding="utf-8"), filename=str(archivo))
        hallazgos += [
            f"{archivo}:{nodo.lineno} -- os.{nodo.attr} fuera de la capa de configuracion"
            for nodo in ast.walk(arbol)
            if isinstance(nodo, ast.Attribute)
            and nodo.attr in _LECTURAS_DE_ENTORNO
            and isinstance(nodo.value, ast.Name)
            and nodo.value.id == "os"
        ]
    return hallazgos


@task
def prohibiciones(c):
    """Prohibiciones del gate ADU comprobables sobre el arbol (RFC-0005, RFC-0001)."""
    hallazgos = _infractores_por_prefijo() + _lecturas_de_entorno_fuera_de_settings()
    if hallazgos:
        detalle = "\n  ".join(hallazgos)
        raise SystemExit(f"Prohibiciones del gate ADU incumplidas:\n  {detalle}")


# Directivas que los artefactos de despliegue TIENEN que declarar (RFC-0020).
# Se comprueban aqui porque el RFC las verifica contra el VPS (CA-4, CA-11,
# CA-13, CA-19) y esa verificacion no puede correr en el repositorio: lo que
# si puede es garantizar que lo que se envia al VPS las trae. Sin esto, borrar
# una linea de la unidad o del vhost no rompe nada visible hasta que alguien
# mide la latencia o audita el host.
_UNIDAD = Path("deploy/rag-cv-api.service")
_VHOST = Path("deploy/nginx/reto.qrimapp.com.conf")
_DESPLIEGUE = Path("deploy/deploy.sh")
_APROVISIONAMIENTO = Path("deploy/provision.sh")

_ARTEFACTOS_DE_DESPLIEGUE: dict[Path, dict[str, str]] = {
    _UNIDAD: {
        # RFC-0020 5.1, equivalencias nativas del endurecimiento perdido con
        # el contenedor (ADR-0010).
        "ProtectSystem=strict": "raiz de solo lectura (5.1 #2)",
        "ReadWritePaths=": "la unica ruta escribible (5.1 #2)",
        "CapabilityBoundingSet=": "capacidades eliminadas (5.1 #3)",
        "RestrictSUIDSGID=yes": "capacidades eliminadas (5.1 #3)",
        "NoNewPrivileges=yes": "no-new-privileges (5.1 #4)",
        # La que el contenedor no daba: impide que una ejecucion remota de
        # codigo a traves de la API lea ~/.ssh y salte a robar la clave.
        "ProtectHome=yes": "el servicio no puede leer /home (5.1, CA-11)",
        "PrivateTmp=yes": "no comparte /tmp (5.1)",
        "ProtectKernelTunables=yes": "sin escritura en /proc/sys (5.1)",
        "ProtectControlGroups=yes": "sin escritura en cgroups (5.1)",
        "MemoryMax=": "limite de memoria (5, CA-8)",
        "CPUWeight=": "peso de CPU (5)",
        "Restart=always": "la API vuelve sola (9)",
        "WantedBy=default.target": "arranca sin sesion abierta (CA-2)",
        "EnvironmentFile=": "el secreto lo lee la unidad, no el perfil (8)",
        "--proxy-headers": "cabeceras de reenvio (7.1)",
        "--forwarded-allow-ips=127.0.0.1": "cabeceras de reenvio (7.1)",
        "--host 127.0.0.1": "la API solo escucha en bucle local (7, CA-4)",
        "--port 8080": "el puerto que nginx alcanza (5)",
    },
    _VHOST: {
        # Sin esto no hay streaming, solo la ilusion: nginx bufferea por
        # defecto y la latencia de primer token pasa a ser la de respuesta
        # completa, sin un solo error en los registros (7.1).
        "proxy_buffering off": "sin esto no hay streaming (7.1, CA-13)",
        "proxy_cache off": "sin cache sobre el flujo (7.1)",
        "gzip off": "comprimir tambien bufferea (7.1)",
        "proxy_read_timeout 300s": "el defecto de 60s corta respuestas largas (7.1)",
        "proxy_http_version 1.1": "requisito de la conexion persistente (7.1)",
        # La expresion regular cubre /v1/chat/stream y /v1/responses: con la
        # ruta literal, el endpoint que registra la plataforma externa caia
        # en la ubicacion generica, con el buffer activo (7.1).
        "chat/stream|responses": "la ubicacion cubre los dos endpoints (7.1, CA-19)",
    },
    _APROVISIONAMIENTO: {
        # Los tres fallos silenciosos de §4. Ninguno emite error: el sistema
        # arranca, responde, y esta mal.
        "--locale-provider=icu": "sin ICU es-MX la busqueda lexica pierde acentos (4, CA-16)",
        "--icu-locale=es-MX": "la configuracion regional se fija AL CREAR la base (4, CA-16)",
        "enable-linger": "sin linger no hay servicio tras un reinicio (4, CA-2)",
        "listen_addresses": "PostgreSQL solo por bucle local (7, CA-4)",
        "datlocprovider": "el aprovisionamiento VERIFICA el ICU, no confia (CA-16)",
        "install -m 600": "el .env nace con permisos restrictivos (8, CA-15)",
    },
    _DESPLIEGUE: {
        # Las exclusiones no son higiene, son seguridad (6).
        "--exclude='.env'": "un .env de desarrollo no viaja al servidor (6, CA-10)",
        "--exclude='corpus/'": "el corpus vive en el VPS (6, RFC-0016 3.3, CA-10)",
        "--exclude='.git'": "el historial no viaja al servidor (6)",
        # `mv -Tf` sobre un enlace simbolico es atomico: no existe un instante
        # en el que `current` apunte a medias (6).
        "mv -Tf": "conmutacion atomica del enlace (6, CA-7)",
        "alembic upgrade head": "la migracion corre ANTES de conmutar (9, CA-6)",
    },
}

# RFC-0020 7: "Que la API escuche en 0.0.0.0 es el fallo grave de esta
# topologia" -- saltaria nginx y con el el TLS. Un `--host 0.0.0.0` copiado
# de un tutorial no falla: el servicio responde igual.
_PROHIBIDO_EN_DESPLIEGUE = {
    "0.0.0.0": "la API o la base escucharian fuera del bucle local (7, CA-4)"
}


def _artefactos_de_despliegue() -> list[str]:
    """RFC-0020: lo que se envia al VPS trae lo que el RFC exige."""
    hallazgos = []
    for archivo, directivas in _ARTEFACTOS_DE_DESPLIEGUE.items():
        if not archivo.exists():
            hallazgos.append(f"{archivo} -- no existe (RFC-0020)")
            continue
        contenido = archivo.read_text(encoding="utf-8")
        hallazgos += [
            f"{archivo} -- falta {directiva!r}: {motivo}"
            for directiva, motivo in directivas.items()
            if directiva not in contenido
        ]
        hallazgos += [
            f"{archivo} -- contiene {prohibido!r}: {motivo}"
            for prohibido, motivo in _PROHIBIDO_EN_DESPLIEGUE.items()
            if prohibido in contenido
        ]
    return hallazgos


@task
def despliegue(c):
    """Los artefactos de RFC-0020 declaran lo que el RFC exige."""
    hallazgos = _artefactos_de_despliegue()
    if hallazgos:
        detalle = "\n  ".join(hallazgos)
        raise SystemExit(f"Artefactos de despliegue incompletos (RFC-0020):\n  {detalle}")


@task
def lint(c):
    # Acotado a codigo Python: "ruff format ." tambien reformatea los
    # bloques de codigo dentro de los RFC en Markdown, que son documentos
    # aprobados y no se tocan fuera del proceso ADU.
    c.run(f"ruff check {_PY_PATHS}")
    c.run(f"ruff format --check {_PY_PATHS}")
    c.run("mypy app/ migrations/")
    prohibiciones(c)
    despliegue(c)


@task
def test(c, kind="unit"):
    c.run(f"pytest -m {kind}")


@task
def evals(c, suite="pr"):
    c.run(f"python evals/run_eval.py --suite {suite}")
