"""Diccionario de sinonimos para tech_tags -- RFC-0002 5.

Unico modulo del repositorio con esta lista (A-7): RFC-0003 5 lo reutilizara
para la expansion de consulta cuando se implemente."""

SYNONYMS: dict[str, str] = {
    "postgres": "postgresql",
    "js": "javascript",
    "k8s": "kubernetes",
}


def normalize_tech_tag(raw: str) -> str:
    tag = raw.strip().lower()
    return SYNONYMS.get(tag, tag)
