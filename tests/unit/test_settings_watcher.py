"""RFC-0019 8: las variables del sondeo, con los valores por defecto del
contrato.

Bloque atomico -> forma de suite completa (RFC-0014 6.1.1): las cuatro
llegan en la misma edicion de Settings y revertirla las enrojece a la vez.

`WATCHER_CADENCE` NO entra en Settings: 8 dice que "no la lee la
aplicacion", la ejecuta el cron. Solo se documenta en .env.example, y eso
tambien se prueba aqui -- una variable de despliegue que nadie documenta es
una que nadie configura.
"""

from pathlib import Path

import pytest

from app.core.settings import Settings

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/test")
    for name in (
        "WATCHER_STABILITY_DELAY_SECONDS",
        "WATCHER_LEASE_SECONDS",
        "WATCHER_MAX_ATTEMPTS",
        "WATCHER_HEARTBEAT_MAX_AGE_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    return Settings(_env_file=None)


def test_watcher_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Los cuatro valores por defecto son los de la tabla de 8."""
    settings = _settings(monkeypatch)

    assert settings.watcher_stability_delay_seconds == 5
    assert settings.watcher_lease_seconds == 600
    assert settings.watcher_max_attempts == 5
    assert settings.watcher_heartbeat_max_age_seconds == 900


def test_watcher_values_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """No son constantes: el VPS ajusta el lease segun lo que tarde una
    reindexacion completa (RFC-0019 5)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/test")
    monkeypatch.setenv("WATCHER_STABILITY_DELAY_SECONDS", "11")
    monkeypatch.setenv("WATCHER_LEASE_SECONDS", "1800")
    monkeypatch.setenv("WATCHER_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("WATCHER_HEARTBEAT_MAX_AGE_SECONDS", "60")

    settings = Settings(_env_file=None)

    assert settings.watcher_stability_delay_seconds == 11
    assert settings.watcher_lease_seconds == 1800
    assert settings.watcher_max_attempts == 2
    assert settings.watcher_heartbeat_max_age_seconds == 60


def test_env_example_documents_every_watcher_variable() -> None:
    """ADU-PROCESO 5: toda variable nueva va a .env.example. Incluida
    WATCHER_CADENCE, que la aplicacion no lee pero el operador si configura."""
    env_example = (_REPO_ROOT / ".env.example").read_text(encoding="utf-8")

    missing = [
        name
        for name in (
            "WATCHER_CADENCE",
            "WATCHER_STABILITY_DELAY_SECONDS",
            "WATCHER_LEASE_SECONDS",
            "WATCHER_MAX_ATTEMPTS",
            "WATCHER_HEARTBEAT_MAX_AGE_SECONDS",
        )
        if f"{name}=" not in env_example
    ]

    assert not missing, f".env.example no documenta: {missing}"


def test_cadence_is_not_read_by_the_application() -> None:
    """RFC-0019 8: la cadencia la ejecuta el cron, no la aplicacion. Si
    apareciera en Settings seria una configuracion que nadie consume y que
    contradice el contrato."""
    assert not hasattr(Settings, "watcher_cadence")
    assert "watcher_cadence" not in Settings.model_fields
