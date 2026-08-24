"""Prompt de sistema versionado del agente -- RFC-0004 4.

SYSTEM_PROMPT_VERSION se incrementa en cada cambio de SYSTEM_PROMPT y se
persiste en cada turno (CA-9): una regresion de calidad se puede atribuir a
una version concreta del prompt.

Placeholder (RFC-0014 3): contenido real en el commit que satisface
RFC-0013 CA-10 -- el 0 y la cadena vacia hacen que la prueba falle por una
razon de comportamiento, no por ImportError.
"""

SYSTEM_PROMPT_VERSION = 0

SYSTEM_PROMPT = ""
