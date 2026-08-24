"""Fabrica de proveedores de modelo (Model Loop) -- RFC-0013 3.

Unico modulo que menciona un proveedor concreto (RFC-0013 A-1): app/agent/
recibe un modelo ya construido y no sabe de donde salio (RFC-0004 CA-6).
"""

from strands.models.model import Model

from app.core.settings import Settings

_PROVEEDORES_VALIDOS = ("bedrock", "anthropic", "openai_compatible")


def build_model(settings: Settings) -> Model:
    """Construye el proveedor de generacion designado por PROVEEDOR.

    Es el unico punto del codigo que conoce proveedores concretos. Anadir
    uno nuevo se hace aqui y en Settings (RFC-0013 4); en ningun otro
    sitio (CA-6, RFC-0004).
    """
    return _construir(settings, settings.proveedor)


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
        from strands.models.openai import OpenAIModel

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
