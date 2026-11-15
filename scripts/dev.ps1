param([switch]$Check)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Create .venv and install .[dev] first; see README.md.'
}
Push-Location -LiteralPath $projectRoot
try {
    if ($Check) {
        & $python -m pytest -c pyproject.toml tests
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & $python -m ruff check .
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & $python -m ruff format --check .
        exit $LASTEXITCODE
    }
    & $python -m rat
    exit $LASTEXITCODE
}
finally { Pop-Location }
