# Diagramas de arquitectura e investigación de costos

Documentos técnicos de la arquitectura de `rag-cv`: hoja de ruta por fases, vista C4,
topología AWS de producción y costos mínimos de implementación en AWS.

Todos los diagramas están en **Mermaid**: GitHub los renderiza como imágenes en cada archivo,
y el script `render.ps1` los exporta a PNG/SVG para incluirlos en informes.

## Contenido

| Documento | Diagrama | Nivel de detalle |
| :--- | :--- | :--- |
| [`hoja-de-ruta.md`](hoja-de-ruta.md) | Hoja de ruta: Fases 1–4 + implementación AWS | Visión de entrega |
| [`arquitectura-c4.md`](arquitectura-c4.md) | C4: Contexto, Contenedor y Componente | Arquitectura de software |
| [`arquitectura-aws.md`](arquitectura-aws.md) | Topología de producción en AWS | Infraestructura |
| [`costos-aws.md`](costos-aws.md) | Costos mínimos de producción | Presupuesto |

## Fuentes normativas

Los diagramas son una **vista**, no una fuente de decisión. La autoridad de diseño está en:

- [`README.md`](../../README.md) — arquitectura objetivo, ingesta e indexación.
- [`docs/PRD.md`](../PRD.md) — requisitos y casos de uso.
- [`docs/rfc/RFC-0001`](../rfc/RFC-0001-arquitectura-general.md) — capas, contratos e invariantes.
- [`docs/rfc/RFC-0007`](../rfc/RFC-0007-entornos-e-infraestructura.md) — entornos, red, IAM y costos.
- [`docs/adr/`](../adr/) — decisiones de cómputo, recuperación, agente, embeddings y proveedor.

## Cómo exportar a imagen

```powershell
# Requiere Node.js 18+ y @mermaid-js/mermaid-cli
.\docs\diagramas\render.ps1
```

Genera los archivos `.svg`/`.png` junto a cada documento.
