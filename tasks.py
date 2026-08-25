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
_CI = Path(".github/workflows/python-tests.yml")
_LOGROTATE = Path("deploy/logrotate.conf")

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
        # La identidad de la release viaja CON la release, no en el .env del
        # operador: el despliegue no debe reescribir el fichero del secreto.
        ".env.release": "la unidad lee la identidad de la release (6, CA-5)",
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
    _CI: {
        # CA-12: sustituto nativo del escaneo de imagen que daba el
        # contenedor (5.1 #9). Sin esto, la unica defensa contra una
        # dependencia con vulnerabilidad conocida es que alguien mire.
        "pip-audit": "pip-audit corre en CI (5.1 #9, CA-12)",
        "requirements.lock": "se audita el lock, no el entorno resuelto (CA-12)",
    },
    _LOGROTATE: {
        # CA-18: la bitacora del sondeo rota y no crece sin limite. Un log
        # que crece sin tope llena el disco del VPS, y el sintoma es que
        # PostgreSQL deja de escribir -- no que falte el log.
        "/opt/rag-cv/logs/": "rota la bitacora del sondeo (CA-18)",
        "rotate": "hay retencion declarada (CA-18)",
        "compress": "las rotadas se comprimen (CA-18)",
    },
    _APROVISIONAMIENTO: {
        # Los tres fallos silenciosos de §4. Ninguno emite error: el sistema
        # arranca, responde, y esta mal.
        "--locale-provider=icu": "sin ICU es-MX la busqueda lexica pierde acentos (4, CA-16)",
        "--icu-locale=es-MX": "la configuracion regional se fija AL CREAR la base (4, CA-16)",
        "enable-linger": "sin linger no hay servicio tras un reinicio (4, CA-2)",
        "listen_addresses": "PostgreSQL solo por bucle local (7, CA-4)",
        "datlocprovider": "el aprovisionamiento VERIFICA el ICU, no confia (CA-16)",
        # `CREATE EXTENSION` exige superusuario y el rol de la aplicacion no
        # lo es -- a proposito. Las crea el aprovisionamiento, que si tiene
        # privilegios; la migracion las encuentra puestas y su
        # `IF NOT EXISTS` se vuelve una operacion vacia (RFC-0006 7).
        "CREATE EXTENSION IF NOT EXISTS vector": "pgvector la crea el aprovisionamiento (RFC-0006 7)",
        "CREATE EXTENSION IF NOT EXISTS unaccent": "unaccent, idem (RFC-0006 7)",
        "CREATE EXTENSION IF NOT EXISTS pg_trgm": "pg_trgm, idem (RFC-0006 7)",
        "CREATE ROLE": "el rol de la aplicacion, que no es superusuario",
        "install -m 600": "el .env nace con permisos restrictivos (8, CA-15)",
        # CA-17: el sondeo de RFC-0019 vive en el crontab del usuario de
        # operacion y corre SIN sudo. Una regla NOPASSWD que lo sostuviera
        # anularia el objetivo entero de RFC-0016 8.1.
        "crontab": "el sondeo de RFC-0019 queda en el crontab del operador (CA-17)",
        "WATCHER_CADENCE": "la cadencia la ejecuta el cron, no la aplicacion (CA-17)",
        # RFC-0019 7: la rotacion va EN ESPACIO DE USUARIO. El fichero de
        # estado propio es lo que la hace posible sin root -- sin `--state`,
        # logrotate escribe en /var/lib y necesita privilegios.
        "--state": "rotacion en espacio de usuario (RFC-0019 7, CA-18)",
        "logrotate.conf": "la configuracion vive en el arbol del operador (RFC-0019 7)",
        # Una comprobacion de seguridad que solo advierte no impone nada: el
        # contrato se impone abortando. Se exige el NOMBRE de la funcion y no
        # un `exit 1` suelto -- el fichero ya tiene otros `exit 1` por motivos
        # distintos, asi que buscarlo a secas daria un verde falso.
        "_abortar_si_hay_sudo_sin_contrasena": "la comprobacion aborta, no avisa (CA-17)",
    },
    _DESPLIEGUE: {
        # Las exclusiones no son higiene, son seguridad (6). Se comprueba la
        # PROPIEDAD -- que el arbol enviado no las lleve -- y no las banderas
        # de una herramienta concreta: `rsync` no existe en Git Bash de
        # Windows, y atar el gate al comando lo haria fallar por el motivo
        # equivocado.
        "_purgar_del_arbol": "el .env y el corpus se borran del arbol enviado (6, CA-10)",
        "PURGA=": "la lista de lo que nunca viaja al servidor (6, CA-10)",
        # `mv -Tf` sobre un enlace simbolico es atomico: no existe un instante
        # en el que `current` apunte a medias (6).
        "mv -Tf": "conmutacion atomica del enlace (6, CA-7)",
        "alembic upgrade head": "la migracion corre ANTES de conmutar (9, CA-6)",
        # El directorio de la release NO tiene .env -- se purga a proposito
        # (6) -- asi que la migracion necesita la URL desde fuera. Se exige
        # la funcion y NO `source`: el `.env` lo parsea `pydantic` con sus
        # reglas, y interpretarlo ademas con bash rompe con cualquier valor
        # que lleve espacios, asteriscos o llaves.
        "_url_de_la_base_del_env": "la URL se lee del .env sin interpretarlo (6, 8)",
        # `requirements.lock` no esta en el repositorio: se genera desde
        # `uv.lock`, que es la unica fuente de verdad de las versiones. Un
        # lock committeado aparte deriva del real sin que nada falle.
        "uv export": "el lock se genera desde uv.lock por release (5.1 #10)",
        "--require-hashes": "las dependencias se instalan por hash (5.1 #9)",
        # `releases/` crece una copia entera por despliegue. Sin retencion,
        # el disco del VPS se llena y el sintoma no es "faltan releases":
        # es que PostgreSQL deja de escribir.
        "COMMIT_SHA": "el despliegue escribe la identidad que /readyz publica (6, CA-5)",
        # El README prometia que el script comprueba el CI y no lo hacia:
        # solo validaba que el SHA existiera. La documentacion de despliegue
        # tiene que describir exactamente las garantias que el script aplica.
        "check-runs": "se comprueba que el SHA tenga CI en verde (6)",
        "_abortar_si_el_ci_no_esta_verde": "y se aborta si no lo esta, no se avisa (6)",
        "_podar_releases": "se retienen N releases, no todas (9)",
        "RETENCION": "cuantas releases se conservan (9)",
    },
}

# RFC-0020 7: "Que la API escuche en 0.0.0.0 es el fallo grave de esta
# topologia" -- saltaria nginx y con el el TLS. Un `--host 0.0.0.0` copiado
# de un tutorial no falla: el servicio responde igual.
# Los literales se componen por la misma razon que los prefijos de arriba: si
# estuvieran escritos enteros, un comentario de este mismo fichero podria
# delatarlo. Para una PROHIBICION el comentario SI cuenta -- es lo contrario
# que para un requisito, y es el error que la auditoria encontro en las dos
# direcciones.
_TODAS_LAS_INTERFACES = "0.0" + ".0.0"

# RFC-0019 §7, literal: "no se toca /etc/logrotate.d, que exigiria root". La
# rotacion del sondeo vive en el arbol del operador, con su propio fichero de
# estado, invocada desde el crontab del usuario.
_LOGROTATE_DEL_SISTEMA = "/etc/" + "logrotate.d"

_PROHIBIDO_EN_DESPLIEGUE = {
    _TODAS_LAS_INTERFACES: "la API o la base escucharian fuera del bucle local (7, CA-4)",
    _LOGROTATE_DEL_SISTEMA: "la rotacion va en espacio de usuario (RFC-0019 7, CA-18)",
}


def _configuracion_efectiva(archivo: Path) -> str:
    """El contenido SIN comentarios: la configuracion que de verdad aplica.

    Un guard por subcadenas sobre el fichero entero acepta una directiva que
    solo aparece comentada. Medido: comentando `ProtectHome=yes` -- la que
    impide que un proceso comprometido de la API lea ~/.ssh -- el guard
    seguia pasando, y el servicio habria corrido sin ella.

    Los tres formatos que se comprueban (unidad de systemd, vhost de nginx y
    guiones de shell) comentan con `#` a principio de linea. Solo se descarta
    el comentario de LINEA COMPLETA: en shell, un `#` a media linea puede ser
    expansion de parametro (`${VAR#patron}`) y no un comentario.
    """
    lineas = archivo.read_text(encoding="utf-8").splitlines()
    return "\n".join(linea for linea in lineas if not linea.lstrip().startswith(("#", ";")))


def _artefactos_de_despliegue() -> list[str]:
    """RFC-0020: lo que se envia al VPS trae lo que el RFC exige.

    Sobre la configuracion EFECTIVA, no sobre el texto del fichero: ver
    `_configuracion_efectiva`."""
    hallazgos = []
    for archivo, directivas in _ARTEFACTOS_DE_DESPLIEGUE.items():
        if not archivo.exists():
            hallazgos.append(f"{archivo} -- no existe (RFC-0020)")
            continue
        contenido = _configuracion_efectiva(archivo)
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
