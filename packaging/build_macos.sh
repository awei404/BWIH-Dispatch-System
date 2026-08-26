#!/bin/zsh
set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# Keep PyInstaller's cache inside the project so it works without access to
# the system Application Support directory.
export PYINSTALLER_CONFIG_DIR="$ROOT_DIR/build/pyinstaller-cache-$(date +%s)"
mkdir -p "$PYINSTALLER_CONFIG_DIR"

python3 -m PyInstaller --noconfirm --clean --onedir \
  --name "BWIH 调度系统" \
  --icon "$ROOT_DIR/packaging/assets/bwih-dispatch.icns" \
  --add-data "templates:templates" \
  --add-data "static:static" \
  --collect-all webview \
  --hidden-import webview.platforms.cocoa \
  --hidden-import openpyxl \
  desktop_app.py

APP_DIR="$ROOT_DIR/release/BWIH调度系统-macOS.app"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Frameworks" "$APP_DIR/Contents/Resources"
cp "$ROOT_DIR/packaging/macos-Info.plist" "$APP_DIR/Contents/Info.plist"
cp "$ROOT_DIR/packaging/assets/bwih-dispatch.icns" "$APP_DIR/Contents/Resources/bwih-dispatch.icns"
cp "$ROOT_DIR/dist/BWIH 调度系统/BWIH 调度系统" "$APP_DIR/Contents/MacOS/BWIH 调度系统"
ditto "$ROOT_DIR/dist/BWIH 调度系统/_internal" "$APP_DIR/Contents/Frameworks"

echo "Created: $APP_DIR"
