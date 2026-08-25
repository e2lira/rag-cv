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

_abortar_si_el_ci_no_esta_verde() {
    # Desplegar a QA un commit sin CI verde es exactamente lo que la
    # identidad de release existe para impedir: /readyz publicaria un SHA
    # que nadie valido, y "desplegamos el commit X" volveria a ser una
    # afirmacion en vez de un hecho (§6, CA-5).
    #
    # **Aborta, no advierte.** Y si falta `gh`, tambien aborta: una garantia
    # que se salta cuando no esta la herramienta no es una garantia. Para el
    # caso legitimo -- desplegar sin red, a sabiendas -- esta `SIN_CI=1`,
    # que hay que escribir a mano y queda en el historial del shell.
    if [[ "${SIN_CI:-0}" == "1" ]]; then
        echo "!! SIN_CI=1: se despliega ${SHA} SIN comprobar el CI, bajo tu responsabilidad" >&2
        return 0
    fi

    command -v gh >/dev/null 2>&1 || {
        echo "!! falta 'gh' y no se puede comprobar el CI de ${SHA}." >&2
        echo "   Instalalo, o repite con SIN_CI=1 si desplegas a sabiendas." >&2
        exit 1
    }

    echo "==> Comprobando el CI de ${SHA}"
    local conclusiones
    # Se mira el codigo de salida de `gh`, no solo su texto: si la llamada
    # falla, su mensaje de error acabaria dentro de `conclusiones` y se
    # reportaria como "no esta en verde" -- aborta igual, pero por el motivo
    # equivocado, y eso manda a depurar al sitio incorrecto.
    if ! conclusiones="$(gh api "repos/:owner/:repo/commits/${SHA}/check-runs" \
        --jq '[.check_runs[] | select(.status=="completed") | .conclusion] | join(" ")' 2>&1)"; then
        echo "!! no se pudo consultar el CI de ${SHA}: ${conclusiones}" >&2
        echo "   Revisa la autenticacion de 'gh', o repite con SIN_CI=1." >&2
        exit 1
    fi

    if [[ -z "${conclusiones}" ]]; then
        echo "!! ${SHA} no tiene ninguna ejecucion de CI completada." >&2
        echo "   Un commit sin evidencia no se despliega a QA." >&2
        exit 1
    fi
    for conclusion in ${conclusiones}; do
        if [[ "${conclusion}" != "success" ]]; then
            echo "!! el CI de ${SHA} no esta en verde: ${conclusiones}" >&2
            exit 1
        fi
    done
    echo "    OK: ${conclusiones}"
}

# El arbol que se envia es el del commit, no el de trabajo: desplegar lo que
# hay en el disco de quien despliega es como se cuela codigo sin revisar.
git rev-parse --verify "${SHA}^{commit}" >/dev/null

_abortar_si_el_ci_no_esta_verde

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
#   .git     El historial no tiene nada que hacer en el servidor. `git
#            archive` ya no lo incluye, pero se purga igual: la garantia no
#            debe depender de un detalle de la herramienta que arma el arbol.
# Rutas exactas, sin comodines: la purga y su verificacion tienen que mirar
# lo MISMO. Con un comodin en la lista, `rm` no lo expande dentro de comillas
# y la verificacion si -- el script abortaria siempre por `.env.example`, que
# es una plantilla versionada con marcadores de posicion y debe viajar.
PURGA=(.env .git corpus)

_purgar_del_arbol() {
    local raiz="$1" objetivo sobrante
    for objetivo in "${PURGA[@]}"; do
        rm -rf "${raiz:?}/${objetivo}"
    done

    # Se COMPRUEBA que no quedo nada, no se confia en el `rm`: es la
    # diferencia entre creer que el secreto no viaja y saberlo (CA-10).
    for objetivo in "${PURGA[@]}"; do
        if [[ -e "${raiz}/${objetivo}" ]]; then
            echo "!! ${objetivo} sigue en el arbol a enviar -- se aborta" >&2
            exit 1
        fi
    done

    # Y cualquier OTRO `.env.<algo>` que no sea la plantilla: `git archive`
    # solo trae ficheros versionados y `.env*` esta en .gitignore, asi que
    # esto no deberia encontrar nada nunca. Existe porque el dia que alguien
    # versione un `.env.produccion` por error, el fallo tiene que ser
    # ruidoso aqui y no silencioso en QA.
    # `.env.example` es una plantilla versionada con marcadores de posicion.
    # `.env.release` lo escribe este mismo script y solo contiene el SHA --
    # es identidad, no secreto. Se declaran aqui y no se confia en el ORDEN
    # de las llamadas: si alguien mueve la escritura antes de la purga, el
    # comportamiento no debe cambiar.
    local permitidos=(.env.example .env.release)
    while IFS= read -r sobrante; do
        local nombre
        nombre="$(basename "${sobrante}")"
        local permitido=0
        for objetivo in "${permitidos[@]}"; do
            [[ "${nombre}" == "${objetivo}" ]] && permitido=1
        done
        [[ "${permitido}" -eq 1 ]] && continue
        echo "!! ${sobrante} parece un fichero de entorno -- se aborta" >&2
        exit 1
    done < <(find "${raiz}" -maxdepth 2 -name '.env*' -type f)
}

_purgar_del_arbol "${ORIGEN}"

# La identidad de la release, que la unidad lee con su segundo
# `EnvironmentFile` y que /readyz publica (§6, CA-5). Va en el arbol de la
# release y NO en el `.env` del operador: son dos cosas con dueños distintos
# -- el secreto lo escribe una persona una vez, la identidad la escribe cada
# despliegue -- y mezclarlas obligaria al despliegue a reescribir el fichero
# que contiene las credenciales.
#
# Sin esto, /readyz devuelve `commit_sha: null` y la comprobacion final de
# este mismo script falla siempre.
printf 'COMMIT_SHA=%s\n' "${SHA}" > "${ORIGEN}/.env.release"

# `tar` sobre `ssh` y no `rsync`. **Desviacion declarada respecto al comando
# literal de §6**: `rsync` no existe en Git Bash de Windows, que es desde
# donde se despliega hoy. Lo normativo de §6 son las propiedades -- que el
# secreto y el corpus no viajen, y que la conmutacion sea atomica --, no la
# herramienta. `--delete` sobra porque cada release va a un directorio NUEVO
# y vacio: la inmutabilidad por release ya da lo que `--delete` daba.
echo "==> Enviando el arbol de ${SHA}"
tar -C "${ORIGEN}" -czf - . \
    | ssh "${DESTINO}" "mkdir -p '${RAG_CV_HOME}/releases/${SHA}' \
        && tar -xzf - -C '${RAG_CV_HOME}/releases/${SHA}'"

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

# `releases/` crece una copia entera del proyecto por despliegue. Sin
# retencion el disco del VPS se llena, y el sintoma no es "faltan releases":
# es que PostgreSQL deja de poder escribir, lejos de la causa.
#
# Se podan DESPUES de conmutar y de reiniciar, nunca antes: si se borraran
# primero y el arranque fallara, no quedaria a donde revertir (§6, CA-7).
# Y nunca se toca la que `current` apunta.
RETENCION="${RETENCION:-5}"

_podar_releases() {
    echo "==> Conservando las ultimas ${RETENCION} releases"
    ssh "${DESTINO}" RAG_CV_HOME="${RAG_CV_HOME}" RETENCION="${RETENCION}" bash -se <<'EOS'
      set -euo pipefail
      VIGENTE="$(readlink -f "${RAG_CV_HOME}/current")"
      cd "${RAG_CV_HOME}/releases"
      # Por fecha de modificacion, de la mas nueva a la mas vieja.
      ls -1dt ./*/ 2>/dev/null | tail -n "+$((RETENCION + 1))" | while read -r vieja; do
          if [[ "$(readlink -f "${vieja}")" == "${VIGENTE}" ]]; then
              echo "    se conserva ${vieja} -- es la vigente"
              continue
          fi
          echo "    borrando ${vieja}"
          rm -rf "${vieja}"
      done
EOS
}

echo "==> Comprobando ${URL_SALUD}"
RESPUESTA="$(curl -fsS --retry 10 --retry-delay 2 --retry-all-errors "${URL_SALUD}")"
echo "${RESPUESTA}"

# La identidad tiene que coincidir, no basta con que responda: si /readyz
# publica otro SHA, el enlace no conmuto o el servicio no reinicio (CA-5).
case "${RESPUESTA}" in
    *"${SHA}"*) echo "==> OK: /readyz publica ${SHA}" ;;
    *) echo "!! /readyz NO publica ${SHA} -- el despliegue no se completo" >&2; exit 1 ;;
esac

# Solo con el despliegue ya verificado: si algo de arriba fallo, las releases
# anteriores siguen intactas y la reversion es posible.
_podar_releases
