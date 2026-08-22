# RFC-0013 — Capa de proveedores de modelo (Model Loop) y parametrización

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aprobado |
| **Depende de** | RFC-0004 |
| **Supersede** | RFC-0004 §3 y §6 (construcción del modelo) |
| **ADRs** | ADR-0005 |
| **Fecha** | 2026-08-22 |

---

## 1. Contexto y problema

RFC-0004 fijaba `BedrockModel` con Claude Sonnet dentro de `build_agent()`. Eso ata el proyecto
a un proveedor en un punto del código, y hace que probar otro modelo sea un cambio de código en
lugar de un cambio de configuración.

El requisito ahora es explícito: **el LLM de generación se designa en la parametrización del
proyecto**, y los candidatos son Bedrock, la API de Anthropic y cualquier endpoint compatible
con OpenAI (DeepSeek, OpenRouter, Groq, Azure OpenAI…). Un solo proveedor activo por despliegue,
elegido por variable de entorno.

Este RFC define esa capa, su contrato, y —lo más importante— **cómo se decide si un cambio de
proveedor es aceptable**: con la suite de evaluación, no con una impresión.

## 2. Alcance

**Entra:** interfaz de la fábrica, las tres ramas de proveedor, contrato de variables de
entorno, gestión de las claves, política de reintentos y fallo, coste, y el gate de evaluación
por proveedor.

**No entra:** el prompt de sistema (RFC-0004 §4, que es **común a todos los proveedores**), los
embeddings (RFC-0012), la infraestructura (RFC-0007).

## 3. La fábrica

Vive en `app/providers/llm.py` y es el **único** lugar del código que menciona un proveedor
concreto. `app/agent/builder.py` recibe un modelo ya construido y no sabe de dónde salió.

```python
def build_model(settings: Settings) -> Model:
    """Construye el proveedor de generación designado por configuración.

    Es el único punto del código que conoce proveedores concretos.
    Añadir uno nuevo se hace aquí y en Settings; en ningún otro sitio.
    """
    proveedor = settings.proveedor

    if proveedor == "bedrock":
        from strands.models import BedrockModel
        return BedrockModel(
            model_id=settings.bedrock_model_id,      # us.anthropic.claude-haiku-4-5-20251001-v1:0
            region_name=settings.aws_region,          # us-east-2
            temperature=settings.llm_temperature,     # 0.3
            max_tokens=settings.llm_max_tokens,       # 1024
            streaming=True,
            boto_client_config=Config(
                retries={"max_attempts": 3, "mode": "adaptive"},
                read_timeout=30, connect_timeout=5,
            ),
        )

    if proveedor == "anthropic":
        from strands.models.anthropic import AnthropicModel
        return AnthropicModel(
            client_args={"api_key": settings.anthropic_api_key.get_secret_value()},
            model_id=settings.anthropic_model_id,     # claude-haiku-4-5
            max_tokens=settings.llm_max_tokens,
            params={"temperature": settings.llm_temperature},
        )

    if proveedor == "openai_compatible":
        # Sirve para OpenAI, Azure OpenAI, DeepSeek, OpenRouter, Groq, etc.
        from strands.models.openai import OpenAIModel
        return OpenAIModel(
            client_args={
                "api_key": settings.openai_compatible_api_key.get_secret_value(),
                "base_url": settings.openai_compatible_base_url,
            },
            model_id=settings.openai_compatible_model_id,
            params={
                "temperature": settings.llm_temperature,
                "max_tokens": settings.llm_max_tokens,
            },
        )

    raise ValueError(f"PROVEEDOR desconocido: {proveedor!r}")
```

Notas de implementación que el Desarrollador debe respetar:

- Los `import` van **dentro de cada rama**: así un despliegue con `PROVEEDOR=openai_compatible`
  no necesita tener instalados `boto3` ni el SDK de Anthropic, y un fallo de dependencia de un
  proveedor no usado no tumba el arranque.
- Los extras de instalación son por proveedor: `strands-agents[anthropic]`,
  `strands-agents[openai]`. Se instalan **todos** en la imagen (son ligeros) para que cambiar de
  proveedor no exija reconstruir, pero se importan solo los que se usan.
- Las claves se tipan como `SecretStr` de Pydantic: no aparecen en un `repr()` accidental ni en
  un volcado de configuración en los logs.
- `streaming=True` es obligatorio en todas las ramas (RNF-1 depende de ello). Si un proveedor no
  lo soporta, no es candidato.

## 4. Contrato de variables de entorno

| Variable | Obligatoria cuando | Ejemplo | Descripción |
| :--- | :--- | :--- | :--- |
| `PROVEEDOR` | siempre | `bedrock` | `bedrock` \| `anthropic` \| `openai_compatible` |
| `LLM_TEMPERATURE` | no | `0.3` | Común a todos los proveedores |
| `LLM_MAX_TOKENS` | no | `1024` | Común a todos los proveedores |
| `AWS_REGION` | `PROVEEDOR=bedrock` | `us-east-2` | Región de Bedrock |
| `BEDROCK_MODEL_ID` | `PROVEEDOR=bedrock` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Perfil de inferencia |
| `ANTHROPIC_API_KEY` | `PROVEEDOR=anthropic` | `sk-ant-…` | Desde Secrets Manager en QA/PROD |
| `ANTHROPIC_MODEL_ID` | `PROVEEDOR=anthropic` | `claude-haiku-4-5` | — |
| `OPENAI_COMPATIBLE_API_KEY` | `PROVEEDOR=openai_compatible` | `sk-…` | Clave del proveedor |
| `OPENAI_COMPATIBLE_BASE_URL` | `PROVEEDOR=openai_compatible` | `https://api.deepseek.com` | Endpoint |
| `OPENAI_COMPATIBLE_MODEL_ID` | `PROVEEDOR=openai_compatible` | `deepseek-chat` | Identificador del modelo |

**Validación cruzada obligatoria en el arranque.** `Settings` implementa un validador de modelo
que exige las variables de la rama activa y **rechaza el arranque** si falta alguna. No vale
descubrirlo en la primera petición:

```python
@model_validator(mode="after")
def _validar_proveedor(self) -> "Settings":
    requeridas = {
        "bedrock": ["aws_region", "bedrock_model_id"],
        "anthropic": ["anthropic_api_key", "anthropic_model_id"],
        "openai_compatible": [
            "openai_compatible_api_key",
            "openai_compatible_base_url",
            "openai_compatible_model_id",
        ],
    }[self.proveedor]
    faltantes = [c for c in requeridas if getattr(self, c, None) in (None, "")]
    if faltantes:
        raise ValueError(f"PROVEEDOR={self.proveedor} exige: {', '.join(faltantes)}")
    return self
```

## 5. Gestión de las claves

| Entorno | Dónde viven | Notas |
| :--- | :--- | :--- |
| DEV (Windows) | `.env` local, git-ignored, protegido por ACL | RFC-0011 §4.5 |
| QA (VPS Ubuntu) | `.env` en `/opt/rag-cv`, permisos 600 | RFC-0007 §5.2 |
| PROD (AWS) | **Secrets Manager** `rag-cv/prod/llm-provider` | Se resuelve al arrancar, nunca como variable en claro del servicio |

Con `PROVEEDOR=anthropic` o `openai_compatible`, **el rol IAM de App Runner ya no necesita
permisos de Bedrock**: solo `secretsmanager:GetSecretValue`. La política de RFC-0007 §7.1 se
recorta en consecuencia, y eso es una reducción real de superficie.

Rotación: misma mecánica que las API Keys de la propia API (RFC-0005 §6.4) — clave nueva en el
secreto, refresco en ≤ 5 min, clave vieja revocada en el proveedor.

## 6. Un proveedor activo, no un enrutado dinámico

La decisión es deliberada: **un despliegue habla con un proveedor**. No hay enrutado por tipo de
pregunta ni conmutación automática en caliente. Razones:

1. **Comparabilidad.** Si dos peticiones idénticas pueden ir a modelos distintos, las métricas
   de calidad, latencia y coste dejan de significar nada, y la evaluación de RFC-0009 deja de
   ser un gate.
2. **Reproducibilidad de incidentes.** "El agente respondió mal" es investigable solo si se sabe
   qué modelo respondió. `model_id` se persiste por turno (RFC-0006 §4.3), pero un enrutado
   añade una variable más que descartar en cada incidencia.
3. **Coste previsible.** Un fallback silencioso a un modelo más caro es la forma más común de
   sorpresa en la factura.

Cambiar de proveedor es un cambio de configuración + un despliegue, y pasa por el gate de §8.

### 6.1 Fallback: disponible, apagado por defecto

Se implementa un `FallbackModel` que envuelve un proveedor primario y uno secundario, activable
con `PROVEEDOR_FALLBACK`. Vacío por defecto. Cuando está activo:

- Solo conmuta ante fallos **de disponibilidad** (throttling agotado, 5xx del proveedor,
  timeout de conexión). Nunca ante un error de validación o de contenido: eso indicaría un
  problema real que el fallback ocultaría.
- Cada conmutación emite la métrica `ProviderFallbacks` y una línea de log de nivel `WARNING`
  con ambos proveedores. Un fallback silencioso es peor que una caída.
- El turno persistido guarda el `model_id` **realmente usado**, no el configurado.

## 7. Comparativa de proveedores

| | Bedrock (Haiku 4.5) | Anthropic API | OpenAI-compatible (DeepSeek) |
| :--- | :--- | :--- | :--- |
| Credencial | Rol IAM (sin claves en PROD) | API Key | API Key |
| Residencia de datos | Región de AWS elegida | Infraestructura de Anthropic | Infraestructura del proveedor |
| Retención para entrenamiento | No | No | **Verificar en los términos del proveedor** |
| Latencia desde App Runner | La más baja (misma nube) | Buena | Variable |
| Coste relativo | Bajo (Haiku) | Bajo (Haiku) | Muy bajo |
| Calidad en uso de herramientas | Alta | Alta | **A medir** (§8) |
| Complejidad operativa | IAM + red | Una clave | Una clave |

**Sobre Claude Haiku 4.5 como modelo designado:** es una elección de coste/latencia razonable y
suficiente para un agente con dos herramientas y un corpus pequeño. Pero es un modelo más
pequeño que Sonnet, y en este sistema los dos comportamientos críticos son **decidir bien
cuándo llamar a la herramienta** y **abstenerse cuando no hay evidencia** (RF-4). Ambos
degradan antes en modelos pequeños. No es una objeción: es exactamente lo que mide la suite de
evaluación. Si Haiku mantiene *groundedness* ≥ 0.90 y abstención correcta ≥ 0.95 sobre el
conjunto dorado, es la elección correcta y además la barata. Si no, la evaluación lo dirá con
números antes de que lo diga un evaluador humano.

**Sobre la residencia de datos:** las preguntas de los usuarios y los fragmentos del CV viajan
al proveedor elegido. Con un CV es información profesional pública, así que el riesgo es bajo,
pero la fila "retención para entrenamiento" debe verificarse en los términos vigentes de
cualquier proveedor antes de designarlo en PROD. Es una comprobación de una vez, y toca hacerla.

## 8. Gate: cambiar de proveedor exige medición

Un cambio de `PROVEEDOR` **no se promueve a PROD sin ejecutar la suite completa de evaluación
con ese proveedor** (RFC-0009). El informe se adjunta al PR con la comparativa contra la línea
base del proveedor anterior:

```bash
python evals/run_eval.py --suite full --label bedrock-haiku45
python evals/run_eval.py --suite full --label deepseek-chat \
       --compare-to evals/baselines/bedrock-haiku45.json
```

Criterio de aceptación del cambio: **todas** las métricas del proveedor candidato cumplen los
umbrales de merge de RFC-0009 §4, y ninguna cae más de 3 puntos porcentuales respecto a la línea
base sin justificación escrita en el PR.

Los informes por proveedor se archivan en `evals/baselines/<proveedor>-<modelo>.json`. Con el
tiempo, esa carpeta es la respuesta documentada a "¿por qué este modelo y no otro?", que es
justamente lo que el reto pide demostrar.

## 9. Fallos y degradación

| Fallo | Detección | Comportamiento |
| :--- | :--- | :--- |
| Falta una variable de la rama activa | Validador de `Settings` | **No arranca** |
| `PROVEEDOR` desconocido | Fábrica | No arranca, con la lista de valores válidos |
| API Key inválida | Primer 401 del proveedor | HTTP 503 + alerta operativa (es configuración, no culpa del usuario) |
| Throttling del proveedor | 429 del proveedor | 3 reintentos con retroceso; luego 503 + `Retry-After` |
| Proveedor caído | 5xx / timeout | Si hay fallback configurado, conmuta y lo registra; si no, 503 |
| Extra de Strands no instalado | `ImportError` en la rama | No arranca, con el nombre del extra a instalar |
| El proveedor no soporta streaming | Al construir | No arranca: RNF-1 lo exige |

## 10. Criterios de aceptación

| # | Criterio | Verificación |
| :--- | :--- | :--- |
| CA-1 | `build_model` devuelve el tipo correcto para cada valor de `PROVEEDOR` | `tests/unit/test_llm_factory.py` parametrizado con los tres |
| CA-2 | `PROVEEDOR` desconocido lanza `ValueError` con los valores válidos | `test_llm_factory.py::test_unknown_provider` |
| CA-3 | Falta una variable de la rama activa ⇒ no arranca | `test_config.py::test_provider_required_vars` (los tres casos) |
| CA-4 | Las claves son `SecretStr` y no aparecen en `repr(settings)` ni en logs | `test_config.py::test_secrets_not_leaked` |
| CA-5 | Los imports de proveedor están dentro de las ramas | `test_llm_factory.py::test_lazy_imports` (simula ausencia de `boto3`) |
| CA-6 | `app/agent/` no menciona ningún proveedor concreto | `grep -rn "Bedrock\|Anthropic\|OpenAI" app/agent/` sin resultados |
| CA-7 | El `model_id` realmente usado se persiste en cada turno | `test_conversation.py::test_model_id_recorded` |
| CA-8 | Con fallback activo, una caída del primario conmuta y emite `ProviderFallbacks` | `test_fallback.py::test_switch_on_unavailability` |
| CA-9 | Con fallback activo, un error de validación **no** conmuta | `test_fallback.py::test_no_switch_on_validation_error` |
| CA-10 | El mismo prompt de sistema se usa con los tres proveedores | `test_agent.py::test_prompt_is_provider_agnostic` |
| CA-11 | `streaming` está activo en las tres ramas | `test_llm_factory.py::test_streaming_enabled` |

## 11. Riesgos

| Riesgo | Mitigación |
| :--- | :--- |
| Cambiar de proveedor degrada la calidad sin que se note | Gate de evaluación obligatorio (§8) con comparativa contra línea base |
| Un modelo pequeño deja de abstenerse correctamente | Categoría `abstencion` del conjunto dorado (10 casos) como gate |
| Fuga de la API Key | `SecretStr`, Secrets Manager en PROD, `gitleaks` en CI, rotación documentada |
| Fallback silencioso que dispara el coste | Apagado por defecto; métrica y log `WARNING` en cada conmutación |
| Diferencias de formato de *tool calling* entre proveedores | Strands normaliza; aun así, la suite adversarial y las pruebas de herramientas se ejecutan por proveedor antes de designarlo |
| Datos del CV enviados a un proveedor con retención | Verificación documental previa a designar el proveedor en PROD (§7) |

## Contrato de auditoría (gate ADU)

| # | Comprobación | Cómo se verifica | Severidad si falla |
| :--- | :--- | :--- | :--- |
| A-1 | `app/providers/llm.py` es el único módulo que nombra proveedores concretos | CA-6 + `grep` global | Bloqueante |
| A-2 | El validador de `Settings` exige las variables de la rama activa | CA-3 | Bloqueante |
| A-3 | Las claves son `SecretStr` y no se registran nunca | CA-4 + revisión de logs de prueba | Bloqueante |
| A-4 | Los imports son perezosos, dentro de cada rama | CA-5 | Mayor |
| A-5 | El prompt de sistema no se bifurca por proveedor | CA-10 | Mayor |
| A-6 | El fallback está apagado por defecto y solo conmuta por indisponibilidad | CA-8, CA-9 | Mayor |
| A-7 | El PR que cambia `PROVEEDOR` adjunta el informe de evaluación comparado | Revisión del PR | Bloqueante |
| A-8 | El `model_id` persistido es el usado, no el configurado | CA-7 | Mayor |
| A-9 | `streaming=True` en las tres ramas | CA-11 | Mayor |
| A-10 | El rol IAM de PROD no conserva permisos de Bedrock si `PROVEEDOR` no es `bedrock` | Lectura del Terraform desplegado | Mayor |
