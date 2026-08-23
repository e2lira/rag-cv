"""Parseo estructural del corpus -- RFC-0002 3, 4.

Compartido entre corpus_validator.py y chunker.py: front-matter YAML y el
arbol de secciones (#) y unidades (##)."""

import re
from dataclasses import dataclass
from typing import Any

import yaml

_FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


@dataclass(frozen=True)
class UnitBlock:
    """Una unidad `##`, con su seccion `#` padre."""

    section: str
    raw_title: str
    body: str


@dataclass(frozen=True)
class SectionBlock:
    """Una seccion `#` que NO tiene ninguna unidad `##` propia -- su cuerpo
    entero es un fragmento (RFC-0002 4: parrafos sueltos bajo un # sin ##
    forman un fragmento propio de esa seccion)."""

    section: str
    body: str


def parse_front_matter(text: str) -> dict[str, Any]:
    match = _FRONT_MATTER_RE.match(text)
    if match is None:
        return {}
    data = yaml.safe_load(match.group(1))
    return data if isinstance(data, dict) else {}


def iter_units(text: str) -> list[UnitBlock]:
    """Todas las unidades `##`, en orden de aparicion."""
    headings = list(_HEADING_RE.finditer(text))
    units: list[UnitBlock] = []
    current_section = ""
    for i, heading in enumerate(headings):
        level, title = heading.group(1), heading.group(2)
        if level == "#":
            current_section = title.strip()
            continue
        if level != "##":
            continue
        body_start = heading.end()
        body_end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        units.append(
            UnitBlock(section=current_section, raw_title=title, body=text[body_start:body_end])
        )
    return units


def iter_sections_without_units(text: str) -> list[SectionBlock]:
    """Secciones `#` sin ninguna unidad `##` propia."""
    headings = list(_HEADING_RE.finditer(text))
    sections_with_units: set[str] = {unit.section for unit in iter_units(text)}
    result: list[SectionBlock] = []
    for i, heading in enumerate(headings):
        level, title = heading.group(1), heading.group(2)
        if level != "#":
            continue
        section = title.strip()
        if section in sections_with_units:
            continue
        body_start = heading.end()
        body_end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        body = text[body_start:body_end].strip()
        if body:
            result.append(SectionBlock(section=section, body=body))
    return result
