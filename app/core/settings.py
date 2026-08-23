"""Configuracion de la aplicacion, leida desde variables de entorno.

Contrato normativo: docs/rfc/RFC-0011-entorno-dev-windows-nativo.md #4.5,
docs/rfc/RFC-0017-embeddings-sin-aws-openai.md #5,
docs/rfc/RFC-0021-arranque-validado-de-la-aplicacion.md #4,
docs/rfc/RFC-0002-ingesta-y-chunking.md #6.
"""

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: SecretStr = Field(alias="OPENAI_API_KEY", min_length=1)
    anthropic_api_key: SecretStr = Field(alias="ANTHROPIC_API_KEY", min_length=1)

    # Sin valor por defecto y a proposito (RFC-0021 4): una URL de base por
    # defecto es una invitacion a arrancar apuntando sin querer a la base
    # equivocada. SecretStr porque, a diferencia de las API keys, trae la
    # credencial embebida en la propia URL (auditoria PR #44, B-1).
    database_url: SecretStr = Field(alias="DATABASE_URL", min_length=1)

    embedder: str = Field(alias="EMBEDDER", default="openai")
    openai_embed_model: str = Field(alias="OPENAI_EMBED_MODEL", default="text-embedding-3-small")
    embedding_dim: int = Field(alias="EMBEDDING_DIM", default=1536)

    # Relativo en DEV, absoluto en QA (RFC-0016 7) -- Path, no una constante.
    corpus_path: Path = Field(alias="CORPUS_PATH", default=Path("corpus/cv.md"))
    # Tope por fragmento antes de embeber (RFC-0002 6, RFC-0012 6): un
    # fragmento que lo supera no se trunca en silencio, la indexacion falla.
    embed_max_tokens: int = Field(alias="EMBED_MAX_TOKENS", default=1800)
