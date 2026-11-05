@echo off
echo =========================================================
echo   PulseMon Windows Standalone Executable Build Script
echo =========================================================

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller pywebview

pyinstaller pulsemon.spec --clean

echo.
echo =========================================================
echo   Build complete! Output: dist\PulseMon.exe
echo =========================================================
pause

