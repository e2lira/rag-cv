"""Fabrica de proveedores de modelo (Model Loop) -- RFC-0013 3.

Unico modulo que menciona un proveedor concreto (RFC-0013 A-1): app/agent/
recibe un modelo ya construido y no sabe de donde salio (RFC-0004 CA-6).
"""

from strands.models import ModelRouter
from strands.models.model import Model
from strands.models.openai import OpenAIModel  # ROTO A PROPOSITO -- ver RFC-0014 6.1.3

from app.core.settings import Settings

_PROVEEDORES_VALIDOS = ("bedrock", "anthropic", "openai_compatible")


def build_model(settings: Settings) -> Model | ModelRouter:
    """Construye el proveedor de generacion designado por PROVEEDOR.

    Es el unico punto del codigo que conoce proveedores concretos. Anadir
    uno nuevo se hace aqui y en Settings (RFC-0013 4); en ningun otro
    sitio (CA-6, RFC-0004).

    Con PROVEEDOR_FALLBACK configurado (vacio por defecto -- ADR-0005),
    envuelve el primario y el secundario en un ModelRouter con
    AvailabilityFallbackStrategy (RFC-0013 6.1, app/providers/fallback.py):
    conmuta solo ante un fallo de disponibilidad, nunca ante un error de
    validacion o de contenido.
    """
    primario = _construir(settings, settings.proveedor)
    if not settings.proveedor_fallback:
        return primario

    from strands.models import RoutingCandidate

    from app.providers.fallback import AvailabilityFallbackStrategy

    secundario = _construir(settings, settings.proveedor_fallback)
    return ModelRouter(
        [
            RoutingCandidate(model=primario, name=settings.proveedor),
            RoutingCandidate(model=secundario, name=settings.proveedor_fallback),
        ],
        strategy=AvailabilityFallbackStrategy(),
    )


def _construir(settings: Settings, proveedor: str) -> Model:
    if proveedor == "bedrock":
        from botocore.config import Config  # type: ignore[import-untyped]
        from strands.models import BedrockModel

        assert settings.aws_region is not None  # RFC-0013 4: exigido por Settings
        assert settings.bedrock_model_id is not None  # RFC-0013 4
        return BedrockModel(
            model_id=settings.bedrock_model_id,
            region_name=settings.aws_region,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            streaming=True,
            boto_client_config=Config(
                retries={"max_attempts": 3, "mode": "adaptive"},
                read_timeout=30,
                connect_timeout=5,
            ),
        )

    if proveedor == "anthropic":
        from strands.models.anthropic import AnthropicModel

        assert settings.anthropic_api_key is not None  # RFC-0013 4: exigido por Settings
        return AnthropicModel(
            client_args={"api_key": settings.anthropic_api_key.get_secret_value()},
            model_id=settings.anthropic_model_id,
            max_tokens=settings.llm_max_tokens,
            params={"temperature": settings.llm_temperature},
        )

    if proveedor == "openai_compatible":
        assert settings.openai_compatible_api_key is not None  # RFC-0013 4: exigido por Settings
        assert settings.openai_compatible_base_url is not None  # RFC-0013 4
        assert settings.openai_compatible_model_id is not None  # RFC-0013 4
        return OpenAIModel(
            client_args={
                "api_key": settings.openai_compatible_api_key.get_secret_value(),
                "base_url": settings.openai_compatible_base_url,
            },
            model_id=settings.openai_compatible_model_id,
            stream=True,
            params={"temperature": settings.llm_temperature, "max_tokens": settings.llm_max_tokens},
        )

    raise ValueError(
        f"PROVEEDOR desconocido: {proveedor!r} (valores validos: {', '.join(_PROVEEDORES_VALIDOS)})"
    )
