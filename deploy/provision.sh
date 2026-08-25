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

    echo "==> Listo. Falta: rellenar el .env y desplegar con deploy/deploy.sh"
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
apt-get install -y postgresql-16 postgresql-16-pgvector python3.12-venv rsync

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
LOCALE="$(sudo -u postgres psql -tAc \
    "SELECT datlocprovider || ' ' || datcollate FROM pg_database WHERE datname='${BASE}'")"
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
