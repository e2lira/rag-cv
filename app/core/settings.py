"""Configuracion de la aplicacion, leida desde variables de entorno.

Contrato normativo: docs/rfc/RFC-0011-entorno-dev-windows-nativo.md #4.5.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = Field(alias="OPENAI_API_KEY", min_length=1)
    anthropic_api_key: str = Field(alias="ANTHROPIC_API_KEY", min_length=1)
