"""Expansion de la consulta lexica -- RFC-0003 3.1.

Distinto de app.ingestion.synonyms.normalize_tech_tag (RFC-0002 5): aquella
es una canonicalizacion 1 a 1 para tech_tags en la ingesta; esta expande un
termino de consulta a si mismo mas todos sus alias, para tsquery.
"""

import re

from app.ingestion.synonyms import SYNONYMS

# Alias -> canonico (k8s -> kubernetes) y canonico -> [alias, ...]
# (kubernetes -> [k8s]), construido una vez al importar el modulo.
_CANONICAL_TO_ALIASES: dict[str, list[str]] = {}
for _alias, _canonical in SYNONYMS.items():
    _CANONICAL_TO_ALIASES.setdefault(_canonical, []).append(_alias)

_TOKEN_RE = re.compile(r"\S+")


def _expand_term(term: str) -> str:
    lowered = term.lower()
    if lowered in SYNONYMS:
        return f"({term} OR {SYNONYMS[lowered]})"
    if lowered in _CANONICAL_TO_ALIASES:
        aliases = " OR ".join(_CANONICAL_TO_ALIASES[lowered])
        return f"({term} OR {aliases})"
    return term


def expand_query_terms(query: str) -> str:
    return _TOKEN_RE.sub(lambda m: _expand_term(m.group(0)), query)
