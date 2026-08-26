@echo off
setlocal
cd /d "%~dp0.."

python -m PyInstaller --noconfirm --clean --onedir --console ^
  --name "BWIH Dispatch" ^
  --icon "packaging\assets\bwih-dispatch.ico" ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --hidden-import openpyxl ^
  desktop_app.py

echo.
echo === Build complete ===
echo Output: dist\BWIH Dispatch\
echo Run:    "dist\BWIH Dispatch\BWIH Dispatch.exe"
endlocal
