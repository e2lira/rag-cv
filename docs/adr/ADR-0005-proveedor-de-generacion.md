# ADR-0005 — Proveedor de generación designado por parametrización, no cableado

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aceptada |
| **Fecha** | 2026-08-22 |
| **Modifica a** | ADR-0003 (Strands sigue siendo la capa de agente) |
| **RFCs afectados** | RFC-0013, RFC-0004, RFC-0007, RFC-0009 |

## Contexto

RFC-0004 fijaba `BedrockModel` con Claude Sonnet dentro de `build_agent()`. Eso ata el proyecto
a un proveedor en un punto del código y convierte "probar otro modelo" en un cambio de código
en vez de un cambio de configuración.

El proyecto tiene acceso a tres vías: Bedrock (con rol IAM, sin claves en producción), la API de
Anthropic y cualquier endpoint compatible con OpenAI (DeepSeek, OpenRouter, Groq, Azure OpenAI).
Ninguna es obviamente superior para este caso: cambian en credenciales, latencia, residencia de
datos y coste.

## Decisión

El proveedor de generación se **designa por configuración** (`PROVEEDOR`), con una fábrica en
`app/providers/llm.py` que es el único módulo del código que menciona un proveedor concreto.
**Un proveedor activo por despliegue**, no enrutado dinámico. El modelo designado inicialmente es
**Claude Haiku 4.5 sobre Bedrock** (`us.anthropic.claude-haiku-4-5-20251001-v1:0`, `us-east-2`).

Cambiar de proveedor exige ejecutar la suite completa de evaluación con el candidato y adjuntar
la comparativa contra la línea base del anterior (RFC-0013 §8).

## Alternativas consideradas

| Alternativa | A favor | En contra | Por qué se descarta |
| :--- | :--- | :--- | :--- |
| **Fábrica por configuración, un proveedor activo** | Cambiar de modelo es configuración + evaluación, no código. Métricas comparables. Incidentes reproducibles | Hay que mantener tres ramas y sus extras de instalación | **Elegida** |
| Proveedor cableado (diseño anterior) | Lo más simple | Probar otro modelo exige tocar código y volver a pasar por auditoría | El reto evalúa precisamente el criterio para elegir e integrar modelos; cablear uno lo esconde |
| Enrutado dinámico por tipo de pregunta | Optimiza coste: preguntas simples a un modelo barato | Si dos peticiones idénticas pueden ir a modelos distintos, las métricas de calidad, latencia y coste dejan de significar nada, y la evaluación deja de ser un gate | Rompe la comparabilidad, que es lo que sostiene el control de calidad |
| Fallback automático siempre activo | Resiliencia ante caída de un proveedor | Un fallback silencioso a un modelo más caro o peor es la forma más común de sorpresa —en la factura y en la calidad— | Se implementa, pero **apagado por defecto** y solo ante indisponibilidad, con métrica y log en cada conmutación |
| LiteLLM como capa universal | Un solo cliente para todos los proveedores | Una dependencia más entre Strands y el proveedor, con su propia superficie de fallo y su propio mapeo de *tool calling* | Strands ya trae los proveedores que hacen falta |

## Consecuencias

**Positivas**

- Probar DeepSeek o la API de Anthropic es cambiar tres variables y correr la evaluación.
- `evals/baselines/<proveedor>-<modelo>.json` acaba siendo la respuesta documentada a "¿por qué
  este modelo y no otro?", que es justo lo que el reto pide demostrar.
- Con `PROVEEDOR` distinto de `bedrock`, el rol IAM de PROD pierde los permisos de Bedrock:
  menos superficie.
- El prompt de sistema es único y agnóstico del proveedor, así que una comparativa mide el
  modelo, no dos prompts distintos.

**Negativas / deuda aceptada**

- Tres ramas que mantener y tres extras de Strands instalados en la imagen.
- Con Haiku 4.5 —un modelo pequeño— los dos comportamientos críticos del sistema (decidir cuándo
  llamar a la herramienta y **abstenerse** sin evidencia) son los primeros en degradar. No es una
  objeción: es exactamente lo que mide la suite de evaluación, y la decisión de mantenerlo o no
  se toma con esos números.
- Con proveedores de API, las preguntas y los fragmentos del CV salen de AWS. Con un CV es
  información profesional pública, pero las condiciones de retención de cada proveedor deben
  verificarse antes de designarlo en PROD.

**Condición de revisión**

Se reabre si: (a) la evaluación muestra que ningún proveedor único cumple los umbrales y hace
falta enrutado; (b) aparece un requisito de residencia de datos que excluya las APIs externas;
o (c) el coste de generación pasa a ser una fracción relevante del presupuesto.
