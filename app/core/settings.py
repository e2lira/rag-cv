"""Configuracion de la aplicacion, leida desde variables de entorno.

Contrato normativo: docs/rfc/RFC-0011-entorno-dev-windows-nativo.md #4.5,
docs/rfc/RFC-0017-embeddings-sin-aws-openai.md #5,
docs/rfc/RFC-0021-arranque-validado-de-la-aplicacion.md #4,
docs/rfc/RFC-0002-ingesta-y-chunking.md #6,
docs/rfc/RFC-0019-deteccion-de-cambios-del-corpus-en-el-vps.md #8,
docs/rfc/RFC-0003-retrieval-hibrido-rrf.md #5.
"""

from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: SecretStr = Field(alias="OPENAI_API_KEY", min_length=1)
    # Condicional a PROVEEDOR=anthropic (RFC-0013 4), no incondicional como
    # antes de este RFC: un despliegue con PROVEEDOR=bedrock u
    # openai_compatible no tiene por que traer esta clave.
    anthropic_api_key: SecretStr | None = Field(alias="ANTHROPIC_API_KEY", default=None)

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

    # Sondeo del corpus (RFC-0019 8). WATCHER_CADENCE no esta aqui a
    # proposito: la cadencia la ejecuta el cron, la aplicacion no la lee.
    watcher_stability_delay_seconds: int = Field(alias="WATCHER_STABILITY_DELAY_SECONDS", default=5)
    # Debe superar una reindexacion completa (RFC-0019 5): si se queda corto,
    # un segundo proceso reclama un trabajo que sigue en curso.
    watcher_lease_seconds: int = Field(alias="WATCHER_LEASE_SECONDS", default=600)
    watcher_max_attempts: int = Field(alias="WATCHER_MAX_ATTEMPTS", default=5)
    # La declara este RFC, la consume la regla de alerta de RFC-0010 (7.2).
    watcher_heartbeat_max_age_seconds: int = Field(
        alias="WATCHER_HEARTBEAT_MAX_AGE_SECONDS", default=900
    )

    # Recuperacion hibrida (RFC-0003 5, 3.4).
    retrieval_candidates: int = Field(alias="RETRIEVAL_CANDIDATES", default=20)
    retrieval_top_k: int = Field(alias="RETRIEVAL_TOP_K", default=5)
    retrieval_ef_search: int = Field(alias="RETRIEVAL_EF_SEARCH", default=40)
    rrf_k: int = Field(alias="RRF_K", default=60)
    retrieval_min_score: float = Field(alias="RETRIEVAL_MIN_SCORE", default=0.016)
    retrieval_timeout_ms: int = Field(alias="RETRIEVAL_TIMEOUT_MS", default=2000)
    retrieval_context_budget: int = Field(alias="RETRIEVAL_CONTEXT_BUDGET", default=2500)
    # Palanca de ajuste mas barata ante sesgo hacia una rama (RFC-0003 3.4).
    # Cambiarlos exige volver a correr la suite de evaluacion (RFC-0009).
    rrf_weight_semantic: float = Field(alias="RRF_WEIGHT_SEMANTIC", default=1.0)
    rrf_weight_lexical: float = Field(alias="RRF_WEIGHT_LEXICAL", default=1.0)

    # Capa de proveedores de modelo (RFC-0013 4). El valor por defecto es
    # anthropic, no el bedrock de RFC-0013 4: RFC-0018 3 lo sustituye para
    # esta PoC, y los dos RFC aterrizan juntos en este PR.
    proveedor: str = Field(alias="PROVEEDOR", default="anthropic")
    # Cota superior, no solo valor por defecto (RFC-0004 3, A-8): los dos
    # son contrato. Sin `le`, un despliegue los excede por configuracion y
    # se sale del envolvente de estabilidad y coste aprobado (RF-10,
    # RNF-5) sin que nada falle. Se acota por arriba y no por igualdad
    # exacta porque lo que A-8 protege es EXCEDER el limite -- un valor
    # menor no compromete ni la estabilidad ni el coste.
    llm_temperature: float = Field(alias="LLM_TEMPERATURE", default=0.3, ge=0.0, le=0.3)
    llm_max_tokens: int = Field(alias="LLM_MAX_TOKENS", default=1024, gt=0, le=1024)

    aws_region: str | None = Field(alias="AWS_REGION", default=None)
    bedrock_model_id: str | None = Field(alias="BEDROCK_MODEL_ID", default=None)

    # RFC-0018 3: el modelo designado para la PoC, version con fecha (no el
    # alias) por ADR-0012.
    anthropic_model_id: str = Field(alias="ANTHROPIC_MODEL_ID", default="claude-haiku-4-5-20251001")

    # SecretStr (CA-4), a diferencia de bedrock_model_id/aws_region: es la
    # unica clave de las tres ramas que todavia no lo era -- bedrock no
    # tiene clave propia, la resuelve el rol IAM o boto_session.
    openai_compatible_api_key: SecretStr | None = Field(
        alias="OPENAI_COMPATIBLE_API_KEY", default=None
    )
    openai_compatible_base_url: str | None = Field(alias="OPENAI_COMPATIBLE_BASE_URL", default=None)
    openai_compatible_model_id: str | None = Field(alias="OPENAI_COMPATIBLE_MODEL_ID", default=None)

    # Apagado por defecto (RFC-0013 6.1, ADR-0005): un despliegue habla con
    # un proveedor salvo designacion explicita de uno secundario.
    proveedor_fallback: str = Field(alias="PROVEEDOR_FALLBACK", default="")

    @model_validator(mode="after")
    def _validar_proveedor(self) -> "Settings":
        """RFC-0013 4: exige las variables de la rama de PROVEEDOR activa.

        Un PROVEEDOR desconocido no se rechaza aqui -- lo hace build_model
        (RFC-0013 9, CA-2), asi que .get(..., []) lo deja pasar sin
        comprobar nada en vez de lanzar KeyError."""
        requeridas = {
            "bedrock": ["aws_region", "bedrock_model_id"],
            "anthropic": ["anthropic_api_key", "anthropic_model_id"],
            "openai_compatible": [
                "openai_compatible_api_key",
                "openai_compatible_base_url",
                "openai_compatible_model_id",
            ],
        }.get(self.proveedor, [])
        faltantes = [c for c in requeridas if getattr(self, c, None) in (None, "")]
        if faltantes:
            raise ValueError(f"PROVEEDOR={self.proveedor} exige: {', '.join(faltantes)}")
        return self
