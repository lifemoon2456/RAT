param([string]$Compiler = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Create .venv and install .[dev,llm,windows-build] first; see README.md.'
}
Push-Location -LiteralPath $projectRoot
try {
    & $python scripts\build_windows.py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if ($Compiler) {
        & $python scripts\prepare_release.py --compiler $Compiler
    } else {
        & $python scripts\prepare_release.py
    }
    exit $LASTEXITCODE
}
finally { Pop-Location }
