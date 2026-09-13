# SPDX-License-Identifier: GPL-3.0-or-later
param([switch]$NoLaunch)
$ErrorActionPreference = 'Stop'
$sourceRoot = $PSScriptRoot
$installRoot = Join-Path $env:LOCALAPPDATA 'Programs\LogiLocal'
if ([IO.Path]::GetFullPath($sourceRoot).TrimEnd('\') -eq [IO.Path]::GetFullPath($installRoot).TrimEnd('\')) {
    throw 'Run this installer from the source checkout.'
}
if (-not (Test-Path -LiteralPath "$sourceRoot\desktop\node_modules\electron\dist\electron.exe")) {
    & "$sourceRoot\Setup-Desktop.ps1"
}
Push-Location "$sourceRoot\desktop"
try {
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed.' }
} finally { Pop-Location }

New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
function Copy-Tree([string]$From, [string]$To) {
    if (-not (Test-Path -LiteralPath $From)) { return }
    & robocopy.exe $From $To /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP /XD __pycache__ .cache | Out-Null
    if ($LASTEXITCODE -gt 7) { throw "Copy failed: $From" }
}
foreach ($folder in @('logilocal','licenses','docs')) {
    Copy-Tree "$sourceRoot\$folder" "$installRoot\$folder"
}
foreach ($folder in @('electron','dist','node_modules')) {
    Copy-Tree "$sourceRoot\desktop\$folder" "$installRoot\desktop\$folder"
}
foreach ($file in @('launch-service.py','Start-LogiLocal.vbs','requirements.txt','LICENSE','THIRD_PARTY_NOTICES.md','README.md')) {
    Copy-Item -LiteralPath "$sourceRoot\$file" -Destination $installRoot -Force
}
Copy-Item -LiteralPath "$sourceRoot\desktop\package.json" -Destination "$installRoot\desktop\package.json" -Force
Copy-Item -LiteralPath "$sourceRoot\desktop\package-lock.json" -Destination "$installRoot\desktop\package-lock.json" -Force
# First install migrates settings, cached firmware and backups. Upgrades retain
# the installation's data instead of overwriting it with development settings.
foreach ($folder in @('local','backups')) {
    if (-not (Test-Path -LiteralPath "$installRoot\$folder")) {
        Copy-Tree "$sourceRoot\$folder" "$installRoot\$folder"
    }
}
if (-not (Test-Path -LiteralPath "$installRoot\.venv\Scripts\python.exe")) {
    & "$sourceRoot\.venv\Scripts\python.exe" -m venv "$installRoot\.venv"
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed.' }
}
& "$installRoot\.venv\Scripts\python.exe" -m pip install -r "$installRoot\requirements.txt" --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
Push-Location $installRoot
try {
    & '.\.venv\Scripts\python.exe' -c 'from logilocal.system import set_service_autostart,set_autostart; set_service_autostart(True); set_autostart(False)'
    if ($LASTEXITCODE -ne 0) { throw 'Startup registration failed.' }
} finally { Pop-Location }
$shortcutShell = New-Object -ComObject WScript.Shell
$menuRoot = Join-Path ([Environment]::GetFolderPath('Programs')) 'Logi Local'
New-Item -ItemType Directory -Path $menuRoot -Force | Out-Null
foreach ($shortcutPath in @((Join-Path $menuRoot 'Logi Local.lnk'), (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Logi Local.lnk'))) {
    $shortcut = $shortcutShell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = "$env:SystemRoot\System32\wscript.exe"
    $shortcut.Arguments = '"' + "$installRoot\Start-LogiLocal.vbs" + '"'
    $shortcut.WorkingDirectory = $installRoot
    $shortcut.IconLocation = "$installRoot\desktop\node_modules\electron\dist\electron.exe,0"
    $shortcut.Description = 'Logi Local settings and Pi assistant'
    $shortcut.Save()
}
Write-Host "Installed: $installRoot"
if (-not $NoLaunch) {
    Start-Process -FilePath 'wscript.exe' -ArgumentList ('"' + "$installRoot\Start-LogiLocal.vbs" + '"') -WindowStyle Hidden
}
