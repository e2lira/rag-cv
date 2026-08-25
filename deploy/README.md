# Despliegue de QA — RFC-0020

Orden de ejecución sobre `reto.qrimapp.com`. **Cada paso dice qué comprobar**: los tres fallos
más caros de esta topología no emiten ningún error.

Estado de partida asumido (ya resuelto en el VPS): PostgreSQL + pgvector instalados, nginx
sirviendo con el *vhost* del panel, DNS apuntando al host, TLS emitido y renovando, acceso `root`.
Por eso **no hay paso de emisión de certificado** y **no se instala Caddy** — un segundo terminador
TLS competiría por los puertos 80 y 443 y no arrancaría (§7.1).

---

## 0. Cómo llega el proyecto al servidor

**No se clona el repositorio en el VPS, y no debe haber un `.git` allí.**

El artefacto es **un commit**, no un checkout. `deploy/deploy.sh` corre **en tu máquina**, arma el
árbol con `git archive <sha>` en un temporal, le quita `.env`, `.git` y `corpus/`, y lo envía por
`tar` sobre `ssh` a `/opt/rag-cv/releases/<sha>/`. Cada release es un directorio nuevo e inmutable.

Clonar en el servidor rompería tres cosas a la vez: dejaría credenciales de `git` en el host,
permitiría un `git pull` que despliega código sin revisar, y haría que `/readyz` publicara un SHA
que nadie validó.

Lo único que sí se copia al servidor a mano, y una sola vez, es la carpeta `deploy/`, porque
`provision.sh` tiene que ejecutarse allí:

```bash
scp -r deploy root@reto.qrimapp.com:/root/rag-cv-deploy
```

> **`rsync` no está en Git Bash de Windows**, así que la transferencia va por `tar` sobre `ssh`.
> Es una desviación declarada respecto al comando literal de RFC-0020 §6: lo normativo son las
> propiedades —que el secreto y el corpus no viajen, y que la conmutación sea atómica—, no la
> herramienta. `--delete` sobra porque cada release estrena directorio.

## 1. Aprovisionamiento, con privilegios

En el VPS, como `root`:

```bash
cd /root/rag-cv-deploy && bash provision.sh
```

Qué hace, y qué mirar en la salida:

| Paso | Comprobar |
| :--- | :--- |
| PostgreSQL solo por bucle local | `listen_addresses = 'localhost'` (CA-4) |
| **Base con ICU `es-MX`** | La línea `i es-MX`. **Si no sale, el script aborta** |
| Cortafuegos | Lo imprime y **no lo toca**: revisá a mano que 5432 no esté abierto |
| `enable-linger` | `Linger=yes` (CA-2) |
| Árbol en `/opt/rag-cv` | Propiedad de `qrimapp-reto` |

> **El paso del ICU es el único irreversible.** La configuración regional se fija **al crear la
> base**. Si `ragcv` ya existe sin ICU, el script te dice que la borres y vuelvas a ejecutarlo —
> hacelo **ahora que está vacía**. Después de la primera migración, recrearla significa perder los
> datos. Y el síntoma de no hacerlo es que `to_tsvector` trocea mal los acentuados y la búsqueda
> léxica deja de encontrar términos con tilde, **sin excepción, sin log y sin alerta** (CA-16).

## 2. Cuenta de operación, sin `sudo`

```bash
cp -r /root/rag-cv-deploy /home/qrimapp-reto/deploy
chown -R qrimapp-reto:qrimapp-reto /home/qrimapp-reto/deploy
sudo -iu qrimapp-reto bash -lc 'bash ~/deploy/provision.sh --usuario'
```

Instala la unidad de usuario, la habilita y crea `/opt/rag-cv/.env` **ya con permisos `600`** —no
se crean y se corrigen después: `touch` seguido de `chmod` deja una ventana real en la que el
fichero es legible por todo el host (§8, CA-15).

## 3. El secreto y el corpus

Rellenar `/opt/rag-cv/.env` a mano. Tres reglas que no son obvias (§8):

- **No se guarda en el panel de control.** Suele materializarse en un fichero legible por el
  usuario del servidor web, fuera del `600` que sí controlamos.
- **No se exporta en `.bashrc`.** Ahí entra en el entorno de cualquier proceso de esa cuenta,
  incluidas las sesiones SSH.
- Si alguna vez se filtra, **se rota en el proveedor**: cambiar el fichero del host no invalida la
  clave.

Valores que cambian respecto de DEV: `DATABASE_URL` apunta a `127.0.0.1`, `CORPUS_PATH` a
`/opt/rag-cv/corpus/cv.md`, `EMBEDDER=openai`, y `COMMIT_SHA` lo escribe el despliegue.

Y **copiar el corpus a `/opt/rag-cv/corpus/cv.md`**. No viaja en el `rsync` a propósito: vive en el
VPS y no en el repositorio (RFC-0016 §3.3), así que sincronizarlo lo pisaría con lo que hubiera en
la máquina de despliegue (CA-10).

## 4. nginx

Instalar el contenido de `deploy/nginx/reto.qrimapp.com.conf` **por el mecanismo de fragmento
personalizado que ofrezca el panel**. No se edita a mano el *vhost* generado: un cambio del panel
lo sobrescribe y el servicio vuelve al comportamiento anterior sin avisar (CA-14).

El bloque del *stream* va **antes** que el genérico.

## 5. Desplegar

**Desde tu máquina**, no desde el VPS:

```bash
./deploy/deploy.sh <sha-validado-en-verde> qrimapp-reto@reto.qrimapp.com
```

El SHA tiene que ser un commit con CI en verde. El script lo verifica, arma el árbol desde
`git archive` —no desde el disco de trabajo—, genera `requirements.lock` desde `uv.lock`, migra
**antes** de conmutar el enlace, y comprueba que `/readyz` publique ese mismo SHA.

> Si la migración falla, `set -e` corta ahí y `current` sigue apuntando a la release anterior, que
> sigue corriendo (§9, CA-6). Ese orden es todo el mecanismo.

## 6. Verificación

```bash
curl -s https://reto.qrimapp.com/readyz | jq
```

Esperado: `status: ready`, `commit_sha` igual al desplegado, y los tres `checks` en `ok`.

**Y la que no se ve en el cuerpo de la respuesta** — el primer byte del flujo tiene que llegar
antes de que termine la respuesta completa (CA-13, CA-19):

```bash
curl -N -s -o /dev/null -w 'primer byte: %{time_starttransfer}s | total: %{time_total}s\n' \
  -H "X-API-Key: $CLAVE" -H 'Content-Type: application/json' \
  -d '{"message":"Que experiencia tiene en AWS?"}' \
  https://reto.qrimapp.com/v1/chat/stream
```

Si `time_starttransfer` ≈ `time_total`, **nginx está buffereando**: el endpoint responde, las
pruebas de contrato pasan, y la latencia de primer token es la de respuesta completa. RNF-1 se cae
sin un solo error en los registros. Es el fallo silencioso de esta capa (§7.1).

Repetir contra `/v1/responses` con `"stream": true`, que es el endpoint que registra la plataforma
externa (CA-19).

## 7. Reversión

```bash
ssh qrimapp-reto@reto.qrimapp.com \
  'ln -sfn /opt/rag-cv/releases/<sha-anterior> /opt/rag-cv/current.new && \
   mv -Tf /opt/rag-cv/current.new /opt/rag-cv/current && \
   systemctl --user restart rag-cv-api'
```

Sin reconstruir nada: `mv -Tf` sobre un enlace simbólico es atómico (CA-7).

---

## Lo que este procedimiento NO garantiza

El SHA garantiza **qué código** corre, no **con qué dependencias del sistema**. La versión de
PostgreSQL, de pgvector y de Python son estado del host. `requirements.lock` fija las de Python; el
resto vive en este procedimiento, y **un procedimiento se desactualiza**. Es la deuda que ADR-0010
aceptó al diferir el contenedor, y está declarada, no resuelta.
