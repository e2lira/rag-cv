"""Vivacidad y preparacion -- RFC-0005 3.1.

La diferencia entre los dos es el punto: `/healthz` dice si el proceso
vive, `/readyz` si puede atender. Confundirlos hace que `systemd` reinicie
por una base de datos caida, que no es un fallo del proceso.
"""

from fastapi import APIRouter

router = APIRouter()


def build_readiness(app_state: object) -> tuple[dict[str, str], bool]:
    """Comprobaciones de `/readyz` y si todas pasan (RFC-0005 3.1).

    Devuelve el detalle por comprobacion, no un booleano suelto: el cliente
    tiene que saber **cual** fallo. No es filtrado de interno (I-6) porque
    son nombres fijos, no trazas ni recursos.
    """
    raise NotImplementedError  # RFC-0005 3.1: pendiente de su propio ciclo
