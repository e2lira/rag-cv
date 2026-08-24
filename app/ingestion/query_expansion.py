"""Expansion de la consulta lexica -- RFC-0003 3.1.

Distinto de app.ingestion.synonyms.normalize_tech_tag (RFC-0002 5): aquella
es una canonicalizacion 1 a 1 para tech_tags en la ingesta; esta expande un
termino de consulta a si mismo mas todos sus alias, para tsquery.
"""


def expand_query_terms(query: str) -> str:
    raise NotImplementedError
