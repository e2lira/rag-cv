"""Compatibilidad de plataforma para el bucle de eventos en Windows.

Contrato normativo: docs/rfc/RFC-0011-entorno-dev-windows-nativo.md #5.1.
"""


def configure_event_loop() -> None:
    raise NotImplementedError


def assert_compatible_loop() -> None:
    raise NotImplementedError
