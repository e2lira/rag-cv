# ADR-0010 — La PoC se despliega de forma nativa en el VPS, sin contenedores

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aceptada |
| **Fecha** | 2026-08-22 |
| **Modifica a** | ADR-0006 (concreta cómo se entrega) |
| **RFCs afectados** | RFC-0020, RFC-0016, RFC-0015, RFC-0007, RFC-0008, RFC-0017, RFC-0019 |

## Contexto

RFC-0007 declara un requisito duro: *"la misma imagen de contenedor corre en QA y en PROD
(RNF-10): la imagen se construye una vez en el CI, se valida en QA y se promueve a PROD por
digest, sin reconstruir"*. Sobre esa base, RFC-0007 §5 define QA como `docker compose` con Caddy,
la API y PostgreSQL, y RFC-0015 diseña el `Dockerfile`, el `.dockerignore`, el `entrypoint.sh` y
los ficheros de composición.

Dos hechos cambian el planteamiento:

1. **ADR-0006 difirió PROD.** Ya no hay un segundo entorno al que promover, así que la promoción
   por *digest* —el motivo por el que la imagen era el artefacto— no tiene destino.
2. **El VPS no tiene Docker instalado y el despliegue se hace por SSH plano.**

El segundo hecho no es un impedimento: hay acceso de administrador y Docker se podría instalar.
Es una decisión sobre qué complejidad merece la pena sostener, y por eso se registra aquí en vez
de asumirse.

Conviene notar algo que ya era cierto antes de este documento: **DEV nunca usó contenedores.**
RFC-0011 define un entorno Windows nativo, sin Docker, y RFC-0007 §4 lo asume explícitamente
("Sin Docker ⇒ sin `testcontainers`", "la imagen no se prueba en local"). La paridad de artefacto
nunca cubrió DEV; cubría QA y PROD. Al desaparecer PROD, cubre un solo entorno — y un artefacto
portátil que solo corre en un sitio no está demostrando portabilidad.

## Decisión

**QA se despliega de forma nativa sobre Ubuntu Server 24.04**: PostgreSQL con pgvector como
paquete del sistema, Ollama como servicio nativo, la aplicación en un entorno virtual de Python
bajo `systemd` de usuario, y Caddy como servicio del sistema terminando TLS. El despliegue se hace
por **SSH**, sincronizando un árbol de fuentes en un commit concreto. El contrato está en RFC-0020.

**El artefacto deja de ser la imagen y pasa a ser el commit.** Es un cambio de identidad del
artefacto, no su desaparición: lo que RNF-10 protegía —que lo que corre en QA sea exactamente lo
que el CI validó— se conserva desplegando un SHA de commit determinado y exponiéndolo en tiempo de
ejecución para poder comprobarlo.

**RFC-0015 queda diferido junto con PROD**, no derogado. El `Dockerfile` y los ficheros de
composición siguen siendo el diseño de empaquetado válido para el día que se cierre ADR-0006.

## Alternativas consideradas

| Alternativa | A favor | En contra | Por qué se descarta |
| :--- | :--- | :--- | :--- |
| **Despliegue nativo por SSH** | Coincide con lo que el VPS ya tiene. Sin demonio de contenedores compitiendo por los 2 núcleos. Sin la pertenencia al grupo `docker`, que **equivale a `root`** (RFC-0016 §8.1). Menos capas entre un fallo y su causa: un `journalctl` y ya | Se pierde la paridad de artefacto y el aislamiento entre servicios. Las dependencias del sistema —versión de PostgreSQL, de pgvector, de Python— pasan a ser estado del host, no del artefacto. Reconstruir el entorno exige un procedimiento, no un `docker compose up` | **Elegida** |
| Instalar Docker y conservar RFC-0007 §5 y RFC-0015 tal cual | Cero documentos que reescribir. Aislamiento real entre servicios. Reconstrucción reproducible. Conserva RNF-10 y el camino a PROD sin fricción | Añade un demonio y ~2 GB de imágenes en un host de 2 núcleos y 8 GB donde el modelo de embeddings ya compite por CPU. La pertenencia al grupo `docker` anula la ventaja de operar sin `root`. Y conserva un requisito —promover por digest— cuyo destino está diferido | Paga la complejidad de la portabilidad entre entornos cuando **solo queda un entorno**. Es la alternativa a reconsiderar primero si se cierra ADR-0006 |
| Podman rootless en lugar de Docker | Aislamiento sin grupo equivalente a `root`; compatible con los ficheros de composición existentes | Otra pieza que instalar y aprender, con sus diferencias de red y de volúmenes respecto a Docker, para un beneficio que en un host de un solo inquilino es pequeño | Complejidad nueva sin un problema nuevo que resolver |
| Empaquetar la aplicación como `.deb` o con `pex` | Despliegue atómico y reversible sin contenedores | Construir el paquete es trabajo de infraestructura que hoy no existe, y el corpus ya obliga a un paso de sincronización aparte | Desproporcionado para una PoC con un único destino de despliegue |

## Consecuencias

**Positivas**

- **Un componente menos compitiendo por 2 núcleos.** Sin demonio de contenedores ni capa de red
  virtual, en un host donde la inferencia de embeddings ya es cómputo local (RFC-0016 §5).
- **La cuenta de operación deja de necesitar el grupo `docker`**, que es equivalente a `root`. La
  decisión de operar como `qrimapp-reto` (RFC-0016 §8.1) pasa a acotar privilegio de verdad, no
  solo el error accidental.
- **Menos capas entre el síntoma y la causa.** Un fallo se diagnostica con `journalctl` y `psql`,
  sin atravesar `docker logs`, redes de composición ni volúmenes.
- El despliegue es el mecanismo que el VPS ya soporta: SSH.

**Negativas / deuda aceptada**

- **RNF-10 deja de verificarse tal como está escrito.** No hay imagen ni promoción por digest. Se
  sustituye por identidad de release mediante SHA de commit, expuesta en tiempo de ejecución
  (RFC-0020). Es un sustituto más débil: garantiza *qué código* corre, no *con qué dependencias*.
- **Las dependencias del sistema pasan a ser estado del host.** La versión de PostgreSQL, de
  pgvector, de Python y del propio Ollama dejan de viajar con el artefacto. Una reinstalación no es
  reproducible sin un procedimiento escrito, y ese procedimiento puede quedar desactualizado —el
  modo de fallo clásico del despliegue nativo.
- **Se pierde el aislamiento entre servicios.** Un proceso desbocado afecta a los demás sin la
  frontera de un contenedor; no hay límites de memoria ni de CPU por servicio salvo los que
  `systemd` imponga explícitamente.
- **El camino a PROD gana fricción.** Cerrar ADR-0006 exigirá construir y validar la imagen de
  RFC-0015, que en QA nunca se habrá ejercitado. Lo que hoy se ahorra se paga entonces.
- **DEV y QA siguen sin paridad**, y ahora sin ninguna capa que la aproxime: Windows nativo frente
  a Ubuntu nativo. El CI en Linux sigue siendo la autoridad de merge (RNF-11), y pasa a ser la
  **única** red de seguridad contra las diferencias de sistema operativo.

## Condición de revisión

Se reabre si: (a) se cierra ADR-0006 y PROD vuelve al alcance, momento en el que RFC-0015 recupera
su vigencia; (b) aparece un segundo entorno o un segundo inquilino en el host, donde el
aislamiento deja de ser opcional; (c) reconstruir el VPS resulta costoso o poco fiable por la
deriva de dependencias del sistema; o (d) el proyecto necesita demostrar portabilidad de artefacto
como criterio de evaluación.
