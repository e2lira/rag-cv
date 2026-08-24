"""Comportamiento del agente en el turno completo -- RFC-0004 11.

Los CA de esta tabla viven juntos en este modulo porque describen la misma
unidad observable (un turno del agente), aunque no todos toquen PostgreSQL:
cada funcion lleva su propia marca (`unit` o `integration`) segun si necesita
`database_url` o no -- no se declara una marca nueva (RFC-0004 12).
"""

import pytest

from app.agent.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_VERSION

_NOMBRES_DE_PROVEEDOR = ("bedrock", "anthropic", "openai", "claude", "gpt")
_SECCIONES_REQUERIDAS = ("FUENTE DE VERDAD", "USO DE HERRAMIENTAS", "FORMA DE RESPONDER", "ALCANCE")


@pytest.mark.unit
def test_prompt_is_provider_agnostic() -> None:
    """RFC-0013 CA-10 heredado (RFC-0004 11): un solo prompt para los tres
    proveedores -- si mencionara uno, dejaria de serlo para los otros dos."""
    contenido = SYSTEM_PROMPT.lower()
    encontrados = [nombre for nombre in _NOMBRES_DE_PROVEEDOR if nombre in contenido]
    assert not encontrados, f"el prompt de sistema menciona proveedores: {encontrados}"


@pytest.mark.unit
def test_system_prompt_has_required_sections_and_version() -> None:
    """A-3/A-4: las cuatro secciones de RFC-0004 4 sin recortes, y una
    version valida que CA-9 pueda persistir."""
    assert SYSTEM_PROMPT_VERSION >= 1
    faltantes = [s for s in _SECCIONES_REQUERIDAS if s not in SYSTEM_PROMPT]
    assert not faltantes, f"faltan secciones del prompt: {faltantes}"
