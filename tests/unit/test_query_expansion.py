"""RFC-0003 3.1: expansion de sinonimos de la consulta lexica.

Distinto del RFC-0002 A-7 (canonicalizacion 1 a 1 para tech_tags en la
ingesta): aqui un termino de consulta se expande a si mismo mas todos sus
alias, para que websearch_to_tsquery encuentre el corpus normalizado."""

import pytest

from app.ingestion.query_expansion import expand_query_terms

pytestmark = pytest.mark.unit


def test_expands_alias_to_canonical_form() -> None:
    """CA-13: 'k8s' se convierte en una consulta que tambien encuentra
    'kubernetes' -- SYNONYMS['k8s'] = 'kubernetes'."""
    expanded = expand_query_terms("k8s")

    assert expanded == "(k8s OR kubernetes)"


def test_expands_canonical_form_to_its_aliases() -> None:
    """La direccion inversa tambien expande: quien escribe 'kubernetes'
    debe encontrar contenido indexado como 'k8s' antes de normalizar."""
    expanded = expand_query_terms("kubernetes")

    assert expanded == "(kubernetes OR k8s)"


def test_terms_without_synonym_pass_through_unchanged() -> None:
    """Un termino fuera del diccionario no se toca -- expandir todo
    introduce ruido que RFC-0003 3.1 prohibe para la rama vectorial y que
    tampoco tiene sentido aqui."""
    expanded = expand_query_terms("Banorte")

    assert expanded == "Banorte"


def test_expands_each_term_of_a_multi_word_query_independently() -> None:
    """Una consulta real trae varias palabras -- cada una se expande por su
    cuenta, no la frase completa como una unidad."""
    expanded = expand_query_terms("k8s en produccion")

    assert expanded == "(k8s OR kubernetes) en produccion"


def test_expansion_is_case_insensitive() -> None:
    """SYNONYMS almacena claves en minuscula (RFC-0002); la consulta de un
    usuario real trae mayusculas."""
    expanded = expand_query_terms("K8S")

    assert expanded == "(K8S OR kubernetes)"
