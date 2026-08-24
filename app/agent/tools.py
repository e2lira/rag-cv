"""Herramientas expuestas al agente -- RFC-0004 5.

search_cv y list_cv_sections son las UNICAS dos herramientas registradas
(A-6): nada de acceso a internet, ejecucion de codigo ni lectura de
archivos. La firma de cada una es parte del contrato -- es lo que el
modelo lee para decidir cuando llamarlas -- y no lleva parametros de
infraestructura (conexion, embedder): eso se resuelve en su propia
implementacion, no en lo que el modelo puede controlar.
"""

from strands import tool


def reset_dependencies() -> None:
    """Fuerza reconstruir pool/embedder en la proxima llamada -- solo para
    pruebas de integracion, que apuntan a una base efimera distinta en cada
    test (RFC-0011 8)."""
    pass  # RFC-0004 5: cuerpo pendiente de su propio ciclo


@tool
async def search_cv(query: str, chunk_types: list[str] | None = None) -> str:
    """Busca en el CV de la persona y devuelve los fragmentos más relevantes.

    Args:
        query: La pregunta o los términos a buscar, en lenguaje natural.
        chunk_types: Filtro opcional. Valores válidos: "experiencia", "proyecto",
            "habilidad", "educacion", "faq", "perfil". Úsalo solo si la pregunta
            se limita claramente a una de esas categorías.

    Returns:
        Un bloque <contexto_cv> con los fragmentos relevantes, o un aviso de que
        no se encontró información.
    """
    raise NotImplementedError  # RFC-0004 5: implementacion pendiente de su propio ciclo


@tool
async def list_cv_sections() -> str:
    """Devuelve el índice del CV: secciones, empresas, puestos y rangos de fechas."""
    raise NotImplementedError  # RFC-0004 5: implementacion pendiente de su propio ciclo
