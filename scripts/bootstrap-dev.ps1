#Requires -Version 5.1
<#
.SYNOPSIS
    Deja el entorno de DEV en Windows listo desde cero. Idempotente.

.DESCRIPTION
    Contrato normativo: docs/rfc/RFC-0011-entorno-dev-windows-nativo.md #7.
    Los pasos 2-5 (extension vector, base de datos, extensiones, verificacion
    de texto en espanol) viven en Python -- scripts/bootstrap_check.py --
    porque esa logica ya esta probada y es compartida con las pruebas de
    integracion. Este script orquesta el resto y no reimplementa nada.
#>

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

function Write-Step {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Cyan
}

Push-Location $repoRoot
try {
    # 1. Verifica versiones (Python 3.12, PostgreSQL >= 16, git)
    #    PostgreSQL >= 16, no exactamente 16: RFC-0011 #4.1.1 -- ninguna
    #    comprobacion de este RFC pide la version exacta del VPS; esa la
    #    hace el job de CI contra pgvector/pgvector:pg16 (RFC-0011 #8).
    Write-Step "[1/10] Verificando versiones..."

    $pyVersion = & py -3.12 --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Python 3.12 no encontrado. 'winget install Python.Python.3.12' (RFC-0011 #3)."
        exit 1
    }
    Write-Host "        $pyVersion"

    $pgVersionOutput = & psql --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "psql no encontrado en PATH. Instalador de EDB (RFC-0011 #4.1)."
        exit 1
    }
    if ($pgVersionOutput -match "(\d+)\.\d+") {
        $pgMajor = [int]$Matches[1]
        if ($pgMajor -lt 16) {
            Write-Error "PostgreSQL $pgMajor detectado; se requiere >= 16 (RFC-0011 #4.1.1)."
            exit 1
        }
    }
    Write-Host "        $pgVersionOutput"

    $gitVersion = & git --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "git no encontrado. 'winget install Git.Git' (RFC-0011 #3)."
        exit 1
    }
    Write-Host "        $gitVersion"

    # 2-5. Extension vector, base de datos, extensiones, verificacion de
    #      texto en espanol -- delegado a Python (RFC-0011 #7, #4.2, #4.3).
    & uv run python scripts/bootstrap_check.py
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Fallo en los pasos 2-5. Ver el mensaje de arriba."
        exit 1
    }

    # 6. Crea el venv, instala dependencias con uv sync
    Write-Step "[6/10] Sincronizando dependencias (uv sync)..."
    & uv sync
    if ($LASTEXITCODE -ne 0) { exit 1 }

    # 7. Copia .env.example a .env si no existe y aplica la ACL
    Write-Step "[7/10] Verificando .env..."
    if (-not (Test-Path ".env")) {
        Copy-Item ".env.example" ".env"
        Write-Host "        .env creado desde .env.example -- completa las claves antes de arrancar."
    } else {
        Write-Host "        .env ya existe, no se toca."
    }
    icacls .env /inheritance:r /grant:r "${env:USERNAME}:(R,W)" | Out-Null

    # 8. alembic upgrade head -- condicional (RFC-0011 #7): RFC-0006 aun no
    #    define el esquema. Se omite con aviso, no es un fallo.
    Write-Step "[8/10] Migraciones..."
    if (Test-Path "alembic.ini") {
        & uv run alembic upgrade head
        if ($LASTEXITCODE -ne 0) { exit 1 }
    } else {
        Write-Host "        aviso: alembic.ini no existe todavia (RFC-0006 sin implementar); se omite."
    }

    # 9. Reindexacion -- condicional (RFC-0011 #7): RFC-0002 aun no existe.
    Write-Step "[9/10] Ingesta del corpus..."
    if (Test-Path "app/ingestion/indexer.py") {
        & uv run python -m app.ingestion.indexer --corpus corpus/cv.md
        if ($LASTEXITCODE -ne 0) { exit 1 }
    } else {
        Write-Host "        aviso: app/ingestion/indexer.py no existe todavia (RFC-0002 sin implementar); se omite."
    }

    # 10. Resumen
    Write-Step "[10/10] Entorno listo."
    Write-Host ""
    Write-Host "Para arrancar:  invoke dev"
    Write-Host "Para probar:    invoke test"
    Write-Host "Para el lint:   invoke lint"
}
finally {
    Pop-Location
}
