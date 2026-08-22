# ADR-0004 — Titan Text Embeddings V2 como modelo por defecto, `nomic-embed-text` como contingencia

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aceptada |
| **Fecha** | 2026-08-22 |
| **RFCs afectados** | RFC-0012, RFC-0002, RFC-0003, RFC-0006, RFC-0007 |

## Contexto

El retrieval necesita un modelo de embeddings. Las restricciones reales del proyecto:

- Es una **prueba de concepto** evaluada por criterio técnico, no un sistema con años de
  operación por delante.
- La **generación ya corre sobre Bedrock** (Claude Haiku 4.5, `us-east-2`, ADR-0005), con rol de
  instancia en producción.
- El corpus está **en español**; las preguntas llegarán en español y en inglés.
- El desarrollo es Windows nativo (RFC-0011), QA un VPS Ubuntu y PROD App Runner.
- El corpus es diminuto: ~60 fragmentos, ~20 000 tokens. **El coste de embeddings es de
  fracciones de centavo al mes con cualquier proveedor**, así que el coste no puede ser un
  criterio de decisión, y presentarlo como tal sería engañarse.

Se evaluó primero `nomic-embed-text-v1.5` por sus pesos abiertos y por estar ya instalado en el
equipo de desarrollo vía Ollama. Esa opción se revisó al concretar cómo se serviría en cada
entorno, y el análisis cambió la conclusión.

## Decisión

Se usa **`amazon.titan-embed-text-v2:0`** (1024 dimensiones, `normalize: true`) vía Bedrock en
`us-east-2`, **el mismo proveedor, credencial y región que la generación**, en DEV, QA y PROD.

El modelo vive detrás de la interfaz `Embedder` con dos métodos asimétricos
(`embed_documents` / `embed_query`), y `nomic-embed-text` queda **implementado y probado** como
contingencia, seleccionable por variable de entorno.

## Alternativas consideradas

| Alternativa | A favor | En contra | Por qué se descarta |
| :--- | :--- | :--- | :--- |
| **Titan V2 vía Bedrock** | Un proveedor, una credencial, una región para todo el sistema. **En PROD no hay ninguna API key**: el rol de instancia cubre generación y embeddings. Multilingüe por diseño. Cuota por cuenta. Disponible en `us-east-2` | Pesos cerrados: si cambia o se retira, la salida es *otro* modelo y hay que reindexar. Concentra generación y embeddings en un solo proveedor. Sin lote: una llamada por texto | **Elegida** |
| Nomic Embedding API | Pesos abiertos (Apache 2.0): el mismo modelo puede autoalojarse. Independiza el retrieval de AWS. Acepta lote | Segunda cuenta, segunda clave, segundos términos que verificar, para un componente que cuesta céntimos. **`v1.5` está entrenado sobre todo en inglés** (el multilingüe es `v2-moe`), y el corpus es español. Límite de tasa **por IP**, y App Runner y los runners de CI comparten IP | El coste de una credencial y un proveedor extra no se justifica en una PoC, y el punto multilingüe va en contra |
| Ollama local en DEV + API en QA/PROD | Desarrollo offline y gratuito | Dos caminos de servicio ⇒ vectores no idénticos (F16 vs canónico), `model_id` dependiente del entorno, y una prueba de concordancia que mantener para siempre | La divergencia entre local y producción es justo la clase de problema que este proyecto está diseñado para evitar |
| Ollama en los tres entornos | Sin coste ni dependencia de API | App Runner no admite contenedores auxiliares: obligaría a ECS Fargate + ALB (rompe RNF-6), a un servicio aparte en la VPC, o a dos procesos en un contenedor | El coste de infraestructura y de operación no lo justifica |
| `sentence-transformers` embebido en la imagen | Sin red en la ruta de consulta | `torch` + pesos ⇒ imagen ~1.1 GB, App Runner a 2 vCPU / 4 GB (~USD 15–20/mes más), arranque en frío de 8–12 s | Paga un coste real por una independencia de red que no se necesita hoy |
| OpenAI `text-embedding-3-small` | Buena calidad, barato | Otro proveedor propietario más, con las mismas desventajas que Nomic y ninguna ventaja adicional | No aporta nada que los otros no den |

## Consecuencias

**Positivas**

- **Cero secretos de API en producción.** El rol de instancia de App Runner cubre generación y
  embeddings; `NOMIC_API_KEY` desaparece de Secrets Manager. En una PoC evaluada por criterio
  operativo, "ningún secreto de larga vida en producción" es mejor respuesta que "dos claves de
  proveedor bien gestionadas".
- **Un solo alta, una sola credencial en DEV**: `aws sso login` y listo, la misma que ya hace
  falta para la generación.
- Homologación total: mismo modelo y misma región en los tres entornos (RNF-12). Un mismo texto
  produce el mismo vector en local y en producción, sin pruebas de concordancia que mantener.
- Soporte multilingüe por diseño, coherente con un corpus en español.
- Cuotas por cuenta y región, no por IP.

**Negativas / deuda aceptada**

- **Bedrock pasa a ser dependencia única** de generación y embeddings: una caída regional afecta
  a las dos. Se acepta porque la degradación a rama léxica (RFC-0003 §6) ya acota el impacto en
  consulta, y porque la contingencia existe y está probada.
- **Pesos cerrados.** Se pierde la posibilidad de autoalojar exactamente el mismo modelo. La
  salida es cambiar a Nomic, que implica otra dimensión (768) y reindexar.
- **Titan no acepta lote**: indexar 60 fragmentos son 60 llamadas. Se resuelve con concurrencia
  acotada, pero es una diferencia operativa frente a un API que sí batchea.
- **No hay desarrollo offline.** DEV necesita credenciales de AWS y red. La contingencia
  `EMBEDDER=ollama` lo permite, a cambio de recrear la columna y reindexar la base local.
- Requiere habilitar el acceso al modelo en la consola de Bedrock por cuenta y región — un paso
  manual fácil de olvidar que produce un `AccessDeniedException` engañoso.

**Lo que hace barata esta decisión**

La contingencia no es una promesa del documento: `NomicApiEmbedder` y `OllamaEmbedder` están
implementadas y **pasan la misma suite de contrato** que Titan (RFC-0012 CA-18). Cambiar es una
variable de entorno más el procedimiento de reindexación de RFC-0012 §7.1.

Y por eso la interfaz **conserva dos métodos aunque Titan sea simétrico**: la contingencia es
asimétrica, y si la interfaz tuviera un método único, activarla obligaría a revisar cada punto de
llamada del sistema buscando cuáles son consultas y cuáles documentos. El coste de mantener la
distinción hoy es cero; el de no tenerla el día del cambio sería una degradación silenciosa de la
calidad.

**Condición de revisión**

Se reabre si: (a) el proyecto deja de ser una PoC y la portabilidad entre nubes pasa a ser un
requisito; (b) se exige que el retrieval no dependa del mismo proveedor que la generación;
(c) la evaluación muestra que la calidad en español de Titan no alcanza los umbrales de
*context recall* de RFC-0009; o (d) AWS retira o encarece el modelo.
