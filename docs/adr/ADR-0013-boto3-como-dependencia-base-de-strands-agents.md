# ADR-0013 — `boto3` como dependencia base de la capa de proveedores

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aceptada |
| **Fecha** | 2026-08-24 |
| **Decide** | Arquitecto |
| **RFCs afectados** | RFC-0013 |

---

## Contexto

RFC-0013 §3 afirma: *"un despliegue con `PROVEEDOR=openai_compatible` no necesita tener instalados
`boto3` ni el SDK de Anthropic"*. Esa afirmación se escribió antes de verificar el paquete real que
`strands-agents` empaqueta, y resultó falsa.

Verificado durante la implementación del PR #73, en tres pasadas sucesivas de auditoría, con
evidencia reproducible en cada una — no una sola comprobación superficial:

1. `strands/models/__init__.py` importa `BedrockModel` de forma incondicional al importar el
   paquete (`from .bedrock import BedrockModel`), junto con `ModelRouter`. Solo `AnthropicModel` y
   `OpenAIModel` son perezosos, vía `__getattr__` a nivel de módulo.
2. Python ejecuta el `__init__.py` de un paquete padre antes de cualquiera de sus submódulos, sin
   excepción — no es una decisión de `strands-agents`, es la mecánica del lenguaje.
3. Prueba definitiva, aislada: `from strands.models.anthropic import AnthropicModel` — lo mínimo
   que la rama `anthropic` necesita en tiempo de ejecución, sin tocar `Model` ni `ModelRouter` en
   absoluto — también carga `boto3`.
4. `boto3` es dependencia **base** de `strands-agents`: llega instalado incluso pidiendo únicamente
   los extras `[anthropic,openai]`, sin un extra `[bedrock]` que se pueda omitir.

No hay ninguna reestructuración de imports en `app/providers/llm.py` que separe "usar la rama
`anthropic`" de "cargar `boto3`". La brecha no es de código de aplicación: es una propiedad del
paquete de terceros del que RFC-0013 decidió depender.

## Decisión

Se acepta `boto3` como dependencia base de la aplicación en las tres ramas de `PROVEEDOR`, y se
corrige RFC-0013 §3 para retirar la afirmación de independencia. La cláusula que sí se sostiene, y
la que RFC-0013 CA-5 pasa a verificar, es más estrecha: **ninguna rama importa el SDK cliente de
la *otra*** (`AnthropicModel` no se carga si el proveedor activo es `openai_compatible`, y
viceversa) — no que el paquete completo evite `boto3`.

## Alternativas consideradas

| Alternativa | A favor | En contra | Por qué se descarta |
| :--- | :--- | :--- | :--- |
| Bypasear la jerarquía de paquetes con `importlib.util.spec_from_file_location`, cargando el submódulo del SDK sin ejecutar `strands/models/__init__.py` | Evitaría `boto3` en teoría | Rompe los imports relativos internos del submódulo (que asume formar parte del paquete `strands.models`); no soportado por `strands-agents`; extremadamente frágil ante cualquier cambio interno del SDK | El costo de mantenimiento supera por mucho el beneficio de una PoC |
| Reemplazar `strands-agents` por una integración manual de cada SDK (Anthropic/OpenAI/Bedrock) sin el framework | Control total sobre qué se importa | Pierde retry, streaming y normalización de *tool calling* que el framework ya resuelve (RFC-0004); reescribe la capa de agente entera, fuera del alcance de RFC-0013 | Cambia el RFC completo, no solo esta cláusula |
| Mantener un *fork* local de `strands-agents` con `boto3` movido a un extra opcional | Resolvería el síntoma exacto | Mantener un fork de una dependencia de terceros para una PoC no se justifica; cada actualización del framework exige rebasear el parche | Deuda de mantenimiento permanente por una molestia, no un riesgo real |
| **Aceptar `boto3` como dependencia base** (elegida) | Cero código adicional; streaming/retry/*tool calling* los sostiene el framework; consistente con que `boto3` ya se instala hoy sin que nadie lo haya notado como problema | El binario de despliegue incluye `boto3` aunque `PROVEEDOR` nunca sea `bedrock` | Es la única opción sin deuda de mantenimiento nueva, y el costo real es bajo (ver Consecuencias) |

## Consecuencias

**Positivas:** ningún código nuevo que mantener; la capa de proveedores sigue siendo la fábrica de
una sola función que RFC-0013 §3 diseñó; `boto3` es una librería liviana y sin efectos secundarios
en reposo.

**Negativas / deuda aceptada:** un despliegue en QA/PROD con `PROVEEDOR=anthropic` instala `boto3`
igual, sin usarlo. No representa superficie de ataque real: RFC-0018 §4 ya retira el usuario IAM
`rag-cv-qa-invoker` y ninguna credencial de AWS vive en el `.env` de esta PoC — `boto3` instalado
sin credenciales activas no puede autenticar nada.

**Condición de revisión:** si una versión futura de `strands-agents` separa `boto3` detrás de un
extra opcional (o si el proyecto deja de depender de `strands-agents` para la capa de
proveedores), reabrir esta decisión y evaluar si RFC-0013 §3 puede volver a su forma original.
