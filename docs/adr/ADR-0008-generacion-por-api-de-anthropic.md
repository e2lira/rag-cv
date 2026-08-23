# ADR-0008 — La generación de la PoC usa la API de Anthropic, no Bedrock

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aceptada |
| **Fecha** | 2026-08-22 |
| **Modifica a** | ADR-0005 (la parametrización sigue intacta; cambia el proveedor designado) |
| **RFCs afectados** | RFC-0018, RFC-0013, RFC-0016, RFC-0009 |

## Contexto

ADR-0005 decidió lo importante y sigue vigente: **el proveedor de generación se designa por
configuración** (`PROVEEDOR`), con una fábrica en `app/providers/llm.py` como único punto del
código que menciona un proveedor concreto. Lo que ese ADR designó *inicialmente* fue Claude
Haiku 4.5 sobre Bedrock, y el motivo era el mismo que sostenía a Titan: en PROD, el rol de
instancia de App Runner cubría generación y embeddings sin ninguna clave.

Con ADR-0006 no hay App Runner, y con ADR-0007 no hay Titan. Bedrock quedaría como la última
razón para mantener una cuenta de AWS, un usuario IAM y sus claves rotables en el `.env` del VPS
—esta vez para un solo componente—.

Hay un detalle que abarata esta decisión y conviene decirlo: **no existe todavía ninguna línea
base medida**. El repositorio contiene documentación y el DDL; la capa de agente no está
implementada. RFC-0013 §8 exige adjuntar una comparativa contra la línea base del proveedor
anterior antes de cambiar, pero no hay proveedor anterior en ejecución: lo que se está fijando es
**cuál es el proveedor con el que se produce la primera línea base**, no una migración.

## Decisión

`PROVEEDOR=anthropic` con **`claude-haiku-4-5` por la API de Anthropic**. Se conserva
deliberadamente el **mismo modelo** que ADR-0005 había designado: cambia el camino de servicio,
no el modelo.

Esa elección es el punto central de este ADR. La PoC cambia el embedder (ADR-0007), y el embedder
es la variable que puede mover la calidad de la recuperación. **Si al mismo tiempo cambiara el
modelo de generación, una caída en las métricas de RFC-0009 sería inatribuible**: no habría forma
de saber si recuperó mal o si redactó mal. Manteniendo Haiku 4.5 fijo, la primera evaluación mide
una sola cosa.

Explorar otros modelos —DeepSeek, Groq, un modelo local— sigue siendo un cambio de tres variables
de entorno más una corrida de evaluación (RFC-0013 §8). Este ADR no lo impide: fija el punto de
partida, que es distinto.

## Alternativas consideradas

| Alternativa | A favor | En contra | Por qué se descarta |
| :--- | :--- | :--- | :--- |
| **API de Anthropic con `claude-haiku-4-5`** | Sale de AWS conservando exactamente el modelo ya designado: una sola variable cambia en toda la PoC. Rama ya prevista en RFC-0013 §3 y §5. Una única credencial. Sin infraestructura que operar | Una clave de larga vida en el `.env` del VPS. Pago por token. Las preguntas y los fragmentos del CV salen hacia un tercero | **Elegida** |
| Mantener Bedrock desde el VPS | Cero cambios de configuración respecto a ADR-0005. Usuario IAM ya especificado en RFC-0007 §5.2 | Sostiene toda la cuenta de AWS, el usuario IAM, sus claves y su rotación a 90 días para un solo componente. Contradice el motivo de ADR-0006 | Es la dependencia que ADR-0006 y ADR-0007 vinieron a eliminar; conservarla por un componente deja el trabajo a medias |
| Endpoint compatible con OpenAI (DeepSeek, Groq, OpenRouter) | Más barato. Rama ya soportada (RFC-0013). Groq da latencias muy bajas | Cambia modelo **y** camino a la vez que cambia el embedder: dos variables, ninguna atribución posible. Obliga a construir la primera línea base con un modelo no evaluado para el caso | Rompe la comparabilidad justo en la corrida que más importa. Queda disponible como siguiente experimento, con la evaluación como gate |
| Generación local en el VPS (7–8B autoalojado) | Coste cero y cero dependencia de nube: la PoC quedaría enteramente autoalojada | **El VPS no tiene capacidad de cómputo para servir un modelo** (ADR-0007 llegó a la misma conclusión para los embeddings). Y los dos comportamientos críticos —decidir cuándo llamar a la herramienta y **abstenerse** sin evidencia— son los primeros en degradar en modelos pequeños, que es precisamente lo que la evaluación mide | El coste de VPS anula el ahorro, y arriesga el criterio que el reto evalúa. Reconsiderable si la evaluación con Haiku fija una línea base contra la cual comparar |
| Fallback automático entre proveedores | Resiliencia si Anthropic falla | Un fallback silencioso a otro modelo sorprende en la factura y en la calidad | Ya decidido en ADR-0005: se implementa pero **apagado por defecto**, con métrica y log en cada conmutación. Este ADR no lo cambia |

## Consecuencias

**Positivas**

- **Cierra la salida de AWS.** Con ADR-0006, ADR-0007 y este ADR, la aplicación no necesita
  credenciales de AWS en ningún entorno. Se retira el usuario IAM `rag-cv-qa-invoker` completo.
- **`AWS_REGION`, `BEDROCK_MODEL_ID` y la habilitación de acceso a modelos en la consola de
  Bedrock desaparecen** de la configuración de la PoC — incluido ese paso manual por cuenta y
  región que producía un `AccessDeniedException` engañoso.
- **La primera evaluación mide una sola variable**: el embedder. Es lo que hace interpretable el
  resultado.
- Demuestra RNF-13 de forma literal: se cambió el proveedor de generación sin tocar código.

**Negativas / deuda aceptada**

- **Un secreto de larga vida** (`ANTHROPIC_API_KEY`) en `$RAG_CV_HOME/.env` con permisos `600`
  (RFC-0016 §8.1), al que ADR-0007 suma el de OpenAI. RNF-8 se cumple —no viven en el
  repositorio— pero se pierde el "cero claves" que el rol de instancia daba en el PROD diferido.
- **Los fragmentos del CV y las preguntas salen hacia un tercero.** Con un CV el impacto es
  acotado, pero es un cambio de residencia de datos y se declara, no se omite.
- **Pago por token sin infraestructura que lo acote.** RNF-5 (≤ USD 0.05 por conversación de 5
  turnos) y el umbral de coste medio por caso de RFC-0009 (≤ USD 0.012) siguen siendo los frenos,
  y ahora son los únicos.
- **El juez de evaluación queda del mismo proveedor que el agente.** RFC-0009 §4.1 exige que el
  juez sea un modelo superior y distinto del que genera, y eso se cumple; pero juez y agente
  compartiendo proveedor comparten sesgos, que es la misma objeción que ADU aplica a sus propios
  roles. `EVAL_JUDGE_PROVEEDOR` es independiente de `PROVEEDOR` (RFC-0009 §4.1) precisamente para
  poder apuntarlo a otro proveedor; hacerlo o no se decide con la calibración de los 15 casos de
  veredicto humano, no por intuición.

## Condición de revisión

Se reabre si: (a) la evaluación con Haiku 4.5 fija una línea base y otro proveedor la supera con
la comparativa de RFC-0013 §8 adjunta; (b) el coste por conversación supera RNF-5; (c) aparece un
requisito de residencia de datos que impida enviar el corpus a un tercero; o (d) el proyecto
vuelve a AWS (ADR-0006), donde ADR-0005 recupera su designación original sin reescribirse.
