$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { & ./setup.ps1 }
Push-Location desktop
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw 'Desktop dependency installation failed.' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed.' }
} finally { Pop-Location }
