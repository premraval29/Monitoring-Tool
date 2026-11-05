#!/usr/bin/env bash
set -e

echo "========================================================="
echo "  PulseMon macOS Standalone Application Build Script"
echo "========================================================="

python3 -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller pywebview

pyinstaller pulsemon.spec --clean

echo ""
echo "========================================================="
echo "  Build complete! Output: dist/PulseMon.app and dist/PulseMon"
echo "========================================================="

