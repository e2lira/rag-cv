#!/usr/bin/env bash
# Despliegue por SSH con identidad de release -- RFC-0020 §6.
#
# El artefacto deja de ser una imagen con digest y pasa a ser UN COMMIT. Para
# que eso signifique algo verificable, el despliegue es por directorios
# inmutables con conmutacion por enlace simbolico.
#
#   ./deploy/deploy.sh <sha> [usuario@host]
#
# El <sha> tiene que ser un commit validado en verde por el CI. La aplicacion
# lo expone en /readyz: sin eso, "desplegamos el commit X" es una afirmacion
# de quien desplego, no un hecho comprobable (CA-5).

set -euo pipefail

SHA="${1:?falta el SHA del commit validado en verde}"
DESTINO="${2:-qrimapp-reto@reto.qrimapp.com}"
RAG_CV_HOME="${RAG_CV_HOME:-/opt/rag-cv}"
URL_SALUD="${URL_SALUD:-https://reto.qrimapp.com/readyz}"

echo "==> Desplegando ${SHA} en ${DESTINO}:${RAG_CV_HOME}"

# El arbol que se envia es el del commit, no el de trabajo: desplegar lo que
# hay en el disco de quien despliega es como se cuela codigo sin revisar.
git rev-parse --verify "${SHA}^{commit}" >/dev/null

ORIGEN="$(mktemp -d)"
trap 'rm -rf "${ORIGEN}"' EXIT
git archive "${SHA}" | tar -x -C "${ORIGEN}"

# `requirements.lock` NO vive en el repositorio: se genera aqui desde
# `uv.lock`, que es la unica fuente de verdad de las versiones. Un lock
# committeado aparte deriva del real sin que nada falle, y el despliegue
# instalaria versiones distintas de las que el CI valido.
#
# Queda dentro del arbol de la release, asi que se archiva con ella (§5.1
# #10, el sustituto del SBOM) y `pip-audit` puede correr sobre el (CA-12).
echo "==> Generando requirements.lock desde uv.lock"
uv export --format requirements-txt --no-dev --no-emit-project \
    --project "${ORIGEN}" > "${ORIGEN}/requirements.lock"
wc -l < "${ORIGEN}/requirements.lock"

# LAS EXCLUSIONES NO SON HIGIENE, SON SEGURIDAD (§6).
#
#   .env     Sin excluirlo, un .env de desarrollo viajaria dentro del arbol
#            de la release y podria cargarse en lugar del .env del host,
#            metiendo credenciales locales en QA sin que nada lo senale.
#            `.dockerignore` cumplia esta funcion con contenedores y aqui no
#            existe (CA-10).
#   corpus/  El corpus VIVE EN EL VPS y no en el repositorio (RFC-0016 §3.3).
#            Sincronizarlo lo pisaria con lo que hubiera en la maquina de
#            despliegue (CA-10).
#   .git     El historial no tiene nada que hacer en el servidor.
rsync -a --delete \
    --exclude='.env' \
    --exclude='.git' \
    --exclude='corpus/' \
    "${ORIGEN}/" "${DESTINO}:${RAG_CV_HOME}/releases/${SHA}/"

ssh "${DESTINO}" RAG_CV_HOME="${RAG_CV_HOME}" SHA="${SHA}" bash -se <<'EOS'
  set -euo pipefail
  cd "${RAG_CV_HOME}/releases/${SHA}"

  # Las dependencias se instalan AHORA, no al arrancar (§5.1 #6): un servicio
  # que descarga en tiempo de ejecucion depende de la red para reiniciarse.
  python3.12 -m venv .venv
  .venv/bin/pip install --require-hashes -r requirements.lock

  # La migracion corre ANTES de conmutar el enlace. Si falla, `set -e` corta
  # aqui y `current` sigue apuntando a la release anterior, que sigue
  # corriendo (§9, CA-6). Ese orden es todo el mecanismo.
  .venv/bin/alembic upgrade head

  # `mv -Tf` sobre un enlace simbolico es ATOMICO: no existe un instante en
  # el que `current` apunte a medias (§6). Es el equivalente al reemplazo
  # atomico que RFC-0019 §4 exige para el corpus, aplicado al codigo.
  ln -sfn "${RAG_CV_HOME}/releases/${SHA}" "${RAG_CV_HOME}/current.new"
  mv -Tf "${RAG_CV_HOME}/current.new" "${RAG_CV_HOME}/current"

  # Sin sudo (RFC-0016 §8.1).
  systemctl --user restart rag-cv-api
EOS

echo "==> Comprobando ${URL_SALUD}"
RESPUESTA="$(curl -fsS --retry 10 --retry-delay 2 --retry-all-errors "${URL_SALUD}")"
echo "${RESPUESTA}"

# La identidad tiene que coincidir, no basta con que responda: si /readyz
# publica otro SHA, el enlace no conmuto o el servicio no reinicio (CA-5).
case "${RESPUESTA}" in
    *"${SHA}"*) echo "==> OK: /readyz publica ${SHA}" ;;
    *) echo "!! /readyz NO publica ${SHA} -- el despliegue no se completo" >&2; exit 1 ;;
esac
