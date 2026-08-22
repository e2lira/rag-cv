# Renderiza los diagramas Mermaid de docs/diagramas a PNG y SVG.
# Requiere: Node.js 18+ y @mermaid-js/mermaid-cli (npx lo descarga automáticamente).
#
# Uso:
#   pwsh -File docs/diagramas/render.ps1
#   pwsh -File docs/diagramas/render.ps1 -Format svg

param(
    [ValidateSet('png', 'svg')]
    [string]$Format = 'png'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$root = Split-Path -Parent $root
$diagrams = Join-Path $root 'docs\diagramas'
$work = Join-Path ([System.IO.Path]::GetTempPath()) 'ragcv-mermaid'

if (-not (Test-Path $work)) { New-Item -ItemType Directory -Path $work | Out-Null }

$files = Get-ChildItem -Path $diagrams -Filter *.md -File

foreach ($file in $files) {
    $content = Get-Content -LiteralPath $file.FullName -Raw
    $matches = [regex]::Matches($content, '```mermaid\r?\n(?<body>[\s\S]*?)\r?\n```')
    $i = 0
    foreach ($m in $matches) {
        $i++
        $body = $m.Groups['body'].Value
        $name = "{0}-{1}" -f $file.BaseName, $i
        $mmd = Join-Path $work "$name.mmd"
        Set-Content -LiteralPath $mmd -Value $body -Encoding UTF8
        & npx -y @mermaid-js/mermaid-cli -i $mmd -o (Join-Path $diagrams "$name.$Format") -b white -s 2
        Write-Host "Rendered $name.$Format"
    }
}

Write-Host "Done. Output in $diagrams"
