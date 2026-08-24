"""Fabrica de proveedores de modelo (Model Loop) -- RFC-0013 3.

Unico modulo que menciona un proveedor concreto (RFC-0013 A-1): app/agent/
recibe un modelo ya construido y no sabe de donde salio (RFC-0004 CA-6).
"""

from strands.models.model import Model

from app.core.settings import Settings


def build_model(settings: Settings) -> Model:
    raise NotImplementedError
