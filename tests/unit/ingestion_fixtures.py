"""Fixture de corpus para tests de ingesta -- nunca corpus/cv.md (RFC-0016 3.3,
el CV real no se versiona ni se lee en pruebas). Datos sinteticos, no personas
reales."""

VALID_CORPUS = """---
persona: "Ana Prueba"
titular: "Full Stack AI Engineer"
ubicacion: "Ciudad de Mexico, Mexico"
actualizado: "2026-08-22"
idiomas_corpus: ["es"]
---

# Perfil

Ingeniera de software con experiencia en sistemas distribuidos y aprendizaje
automatico aplicado.

# Experiencia

## Empresa Uno -- Ingeniera de Datos Senior            <!-- 2022-03 .. 2025-11 -->
**Contexto:** Plataforma de datos para banca minorista.
**Responsabilidad:** Liderazgo tecnico de un equipo de 4 personas.
**Logros:**
- Redujo el tiempo de ingesta en 40%.
**Stack:** Python, FastAPI, AWS, PostgreSQL

## Empresa Dos -- Desarrolladora Backend                 <!-- 2019-01 .. 2022-02 -->
**Contexto:** Comercio electronico.
**Responsabilidad:** APIs de catalogo y pagos.
**Logros:**
- Migro el monolito a microservicios.
**Stack:** Java, Spring, MySQL

# Proyectos

## Buscador semantico de CVs
**Problema:** Encontrar candidatos por habilidades, no por palabras clave.
**Decision tecnica:** Embeddings + PostgreSQL con pgvector.
**Resultado:** Reduccion del 60% en tiempo de filtrado manual.
**Stack:** Python, OpenAI, PostgreSQL

# Habilidades

## Lenguajes y frameworks
Python, TypeScript, FastAPI, React

## Cloud e infraestructura
AWS, Docker, Terraform

## Datos e IA
PostgreSQL, pgvector, RAG, LLMs

# Educacion y certificaciones

## Ingenieria en Sistemas -- Universidad Ejemplo          <!-- 2014-08 .. 2019-06 -->
Titulo profesional.

# Preguntas frecuentes

## ¿Esta disponible para reubicacion?
Si, dentro de Mexico.

## ¿Que modalidad de trabajo prefiere?
Remoto o hibrido.
"""
