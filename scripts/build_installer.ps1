param([string]$Compiler = 'ISCC.exe')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
Push-Location -LiteralPath $projectRoot
try {
    if (-not (Test-Path -LiteralPath 'dist\RAT.exe')) { throw 'Build RAT.exe first.' }
    $releaseVersion = & $python -c 'from rat import __version__; print(__version__)'
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read RAT version.' }
    & $Compiler "/DAppVersion=$releaseVersion" 'scripts\installer.iss'
    if ($LASTEXITCODE -ne 0) { throw 'Installer compiler failed.' }
}
finally { Pop-Location }
