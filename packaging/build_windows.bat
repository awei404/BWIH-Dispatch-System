@echo off
setlocal
cd /d "%~dp0.."

python -m PyInstaller --noconfirm --clean --windowed --onefile ^
  --name "BWIH Dispatch" ^
  --icon "packaging\assets\bwih-dispatch.ico" ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --collect-all webview ^
  --hidden-import webview.platforms.edgechromium ^
  --hidden-import openpyxl ^
  desktop_app.py

echo Created: dist\BWIH Dispatch.exe
endlocal
