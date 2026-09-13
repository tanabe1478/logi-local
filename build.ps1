$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& '.\.venv\Scripts\python.exe' -m pip install pyinstaller==6.16.0
if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed.' }
& '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --onefile --windowed --name LogiLocal --distpath . --hidden-import pystray._win32 launch.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }
