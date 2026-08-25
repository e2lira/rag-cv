#!/usr/bin/env bash
# Aprovisionamiento del VPS -- RFC-0020 §4. UNA VEZ POR VPS, con privilegios.
#
#   sudo ./provision.sh            # pasos que necesitan root
#   ./provision.sh --usuario       # pasos de la cuenta de operacion (sin sudo)
#
# Los tres fallos que este script previene NO EMITEN NINGUN ERROR. El sistema
# arranca, responde, y esta mal:
#
#   1. Base sin ICU es-MX  -> `to_tsvector` trocea mal los acentuados y la
#      rama lexica de RFC-0003 deja de encontrar terminos con tilde. Sin
#      excepcion, sin log, sin alerta: el agente responde peor y nadie sabe
#      por que. Y NO SE PUEDE ARREGLAR DESPUES sin recrear la base (CA-16).
#   2. Sin `enable-linger`  -> las unidades de usuario mueren al cerrar la
#      sesion SSH y no arrancan al iniciar el host. El VPS se reinicia de
#      madrugada y por la manana no hay servicio (CA-2).
#   3. PostgreSQL fuera del bucle local -> RNF-7 roto en silencio (CA-4).

set -euo pipefail

USUARIO="${USUARIO:-qrimapp-reto}"
RAG_CV_HOME="${RAG_CV_HOME:-/opt/rag-cv}"
BASE="${BASE:-ragcv}"

_abortar_si_hay_sudo_sin_contrasena() {
    # CA-17: el sondeo corre SIN sudo, y sin ninguna regla `NOPASSWD` que lo
    # sostenga -- una regla asi anularia el objetivo entero de RFC-0016 §8.1.
    #
    # **Aborta, no advierte.** Una comprobacion de seguridad que solo imprime
    # un aviso no impone nada: el aprovisionamiento termina en verde, nadie
    # lee la linea, y la regla sigue ahi. Si el contrato dice que no puede
    # haber, la unica forma de imponerlo es fallar.
    echo "==> Comprobando que no haya sudo sin contrasena para esta cuenta (CA-17)"
    if sudo -n -l >/dev/null 2>&1; then
        echo "!! ${USER:-esta cuenta} puede usar sudo SIN contrasena." >&2
        echo "   CA-17 exige que el sondeo no se sostenga en una regla NOPASSWD." >&2
        echo "   Quitala de /etc/sudoers.d/ y vuelve a ejecutar." >&2
        exit 1
    fi
    echo "    OK: sin sudo sin contrasena"
}

# ---------------------------------------------------------------------------
# Pasos de la cuenta de operacion -- sin sudo (RFC-0016 §8.1)
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--usuario" ]]; then
    echo "==> Instalando la unidad de usuario"
    install -d "${HOME}/.config/systemd/user"
    install -m 644 "$(dirname "$0")/rag-cv-api.service" \
        "${HOME}/.config/systemd/user/rag-cv-api.service"
    systemctl --user daemon-reload
    systemctl --user enable rag-cv-api

    echo "==> El .env nace con permisos 600, no se corrigen despues (§8)"
    # `touch` seguido de `chmod 600` deja una ventana -- corta, pero real --
    # en la que el fichero es legible por todo el host.
    if [[ ! -f "${RAG_CV_HOME}/.env" ]]; then
        install -m 600 /dev/null "${RAG_CV_HOME}/.env"
        echo "    creado vacio en ${RAG_CV_HOME}/.env -- rellenarlo a mano"
        echo "    NO se guarda en el panel de control ni se exporta en .bashrc (§8)"
    fi
    ls -l "${RAG_CV_HOME}/.env"

    echo "==> Sondeo del corpus en el crontab del operador (CA-17)"
    # RFC-0019 corre desde el cron del USUARIO, sin sudo y sin ninguna regla
    # NOPASSWD que lo sostenga: una regla asi anularia el objetivo entero de
    # RFC-0016 §8.1. La cadencia la ejecuta el cron, no la aplicacion --
    # `WATCHER_CADENCE` esta a proposito fuera de `Settings`.
    WATCHER_CADENCE="${WATCHER_CADENCE:-*/5 * * * *}"
    LINEA="${WATCHER_CADENCE} cd ${RAG_CV_HOME}/current && .venv/bin/python -m app.ingestion.watcher >> ${RAG_CV_HOME}/logs/watcher.log 2>&1"
    if crontab -l 2>/dev/null | grep -q 'app.ingestion.watcher'; then
        echo "    ya estaba en el crontab -- no se duplica"
    else
        { crontab -l 2>/dev/null; echo "${LINEA}"; } | crontab -
    fi
    crontab -l | grep 'app.ingestion.watcher'

    echo "==> Rotacion de la bitacora, EN ESPACIO DE USUARIO (RFC-0019 §7, CA-18)"
    # No en el directorio de logrotate del sistema: eso exigiria root, y el
    # sondeo entero existe para correr sin privilegios (RFC-0016 §8.1). El
    # fichero de estado propio es lo que lo hace posible.
    install -m 644 "$(dirname "$0")/logrotate.conf" "${RAG_CV_HOME}/logs/logrotate.conf"
    LINEA_ROTACION="0 4 * * * /usr/sbin/logrotate --state ${RAG_CV_HOME}/logs/.logrotate.state ${RAG_CV_HOME}/logs/logrotate.conf"
    if crontab -l 2>/dev/null | grep -q 'logrotate.conf'; then
        echo "    ya estaba en el crontab -- no se duplica"
    else
        { crontab -l 2>/dev/null; echo "${LINEA_ROTACION}"; } | crontab -
    fi
    /usr/sbin/logrotate --debug --state "${RAG_CV_HOME}/logs/.logrotate.state" \
        "${RAG_CV_HOME}/logs/logrotate.conf" >/dev/null && echo "    configuracion valida"

    _abortar_si_hay_sudo_sin_contrasena

    echo "==> Listo. Falta: rellenar el .env, copiar el corpus y desplegar"
    exit 0
fi

# ---------------------------------------------------------------------------
# Pasos con privilegios
# ---------------------------------------------------------------------------
[[ "${EUID}" -eq 0 ]] || { echo "!! estos pasos necesitan root; usa sudo" >&2; exit 1; }

echo "==> 1. Paquetes del sistema"
# nginx YA esta instalado y sirviendo, gestionado por el panel: no se toca.
# Y sobre todo NO se instala Caddy, que competiria por los puertos 80 y 443.
# No se instala ningun motor de inferencia: los embeddings van por API
# (ADR-0007) y la generacion tambien (ADR-0008). El host solo corre la
# aplicacion (CA-3).
apt-get install -y postgresql-16 postgresql-16-pgvector python3.12-venv

echo "==> 2. PostgreSQL solo por bucle local (§7, CA-4)"
CONF="$(sudo -u postgres psql -tAc 'SHOW config_file')"
if grep -qE "^[[:space:]]*#?[[:space:]]*listen_addresses" "${CONF}"; then
    sed -i "s|^[[:space:]]*#\?[[:space:]]*listen_addresses.*|listen_addresses = 'localhost'|" "${CONF}"
else
    echo "listen_addresses = 'localhost'" >> "${CONF}"
fi
grep -E "^listen_addresses" "${CONF}"
systemctl restart postgresql

echo "==> 2b. La base, CON PROVEEDOR ICU es-MX"
# Su propio paso y no una linea mas: la configuracion regional se fija AL
# CREAR la base y no se puede cambiar despues sin recrearla. Ver la cabecera.
if sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${BASE}'" | grep -q 1; then
    echo "    la base ya existe -- se verifica, no se recrea"
else
    sudo -u postgres createdb "${BASE}" \
        --encoding=UTF8 --locale-provider=icu --icu-locale=es-MX --template=template0
fi

# Se VERIFICA, no se confia en que quien aprovisiona se acuerde (CA-16).
#
# La locale de ICU **no vive en `datcollate`** (ADR-0019): ahi esta la de
# libc, heredada del servidor, que vale distinto en cada host y no dice nada
# sobre ICU. Compararla contra `es-MX` no falla ruidosamente -- simplemente
# no coincide nunca, y la rama de fallo ordena `dropdb` sobre una base
# correcta. Es peor que no comprobar.
#
# Y el nombre de la columna cambia con la version, asi que se le pregunta al
# servidor en vez de fijar uno: `daticulocale` en PG 15-16, `datlocale` en
# PG >= 17. Un nombre fijo falla al actualizar con `UndefinedColumn`, que
# parece un problema de permisos y manda a depurar al sitio equivocado.
COLUMNA_ICU="$(sudo -u postgres psql -tAc \
    "SELECT attname FROM pg_attribute WHERE attrelid='pg_database'::regclass \
     AND attname IN ('daticulocale','datlocale')")"

if [[ -z "${COLUMNA_ICU}" ]]; then
    echo "!! este PostgreSQL no expone la locale de ICU por base." >&2
    echo "   Se necesita PostgreSQL >= 15 para el proveedor ICU (RFC-0020 §4)." >&2
    exit 1
fi

LOCALE="$(sudo -u postgres psql -tAc \
    "SELECT datlocprovider::text || ' ' || COALESCE(${COLUMNA_ICU}, '(ninguna)') \
     FROM pg_database WHERE datname='${BASE}'")"
echo "    ${LOCALE}"
case "${LOCALE}" in
    i\ es-MX*) echo "    OK: proveedor ICU con es-MX" ;;
    *) echo "!! la base NO tiene ICU es-MX. Hay que RECREARLA ahora que esta vacia:" >&2
       echo "     sudo -u postgres dropdb ${BASE} && vuelve a ejecutar este script" >&2
       exit 1 ;;
esac

echo "==> 3. Cortafuegos: VERIFICAR antes de tocar"
# Si el VPS trae panel de control, el cortafuegos puede estar gestionado por
# el: un `ufw enable` a ciegas puede dejarte fuera o romper reglas existentes.
ufw status verbose || true
echo "    revisar a mano que 5432 NO este abierto y que 22/80/443 sigan como estaban"

echo "==> 4. Las unidades de usuario arrancan sin sesion abierta (CA-2)"
loginctl enable-linger "${USUARIO}"
loginctl show-user "${USUARIO}" -p Linger

echo "==> 5. Arbol de despliegue, propiedad del operador"
install -d -o "${USUARIO}" -g "${USUARIO}" \
    "${RAG_CV_HOME}" "${RAG_CV_HOME}/releases" "${RAG_CV_HOME}/corpus" "${RAG_CV_HOME}/logs"
ls -ld "${RAG_CV_HOME}"/*

echo
echo "==> Pasos con privilegios completados."
echo "    Ahora, COMO ${USUARIO} y sin sudo:  ./provision.sh --usuario"
echo "    Despues: copiar el corpus a ${RAG_CV_HOME}/corpus/cv.md (no viaja en el rsync)"
