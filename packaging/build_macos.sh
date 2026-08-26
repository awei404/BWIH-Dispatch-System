#!/bin/zsh
set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

export PYINSTALLER_CONFIG_DIR="$ROOT_DIR/build/pyinstaller-cache-$(date +%s)"
mkdir -p "$PYINSTALLER_CONFIG_DIR"

python3 -m PyInstaller --noconfirm --clean --onedir \
  --name "BWIH Dispatch" \
  --icon "$ROOT_DIR/packaging/assets/bwih-dispatch.icns" \
  --add-data "templates:templates" \
  --add-data "static:static" \
  --hidden-import openpyxl \
  desktop_app.py

APP_DIR="$ROOT_DIR/release/BWIH调度系统.app"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Frameworks" "$APP_DIR/Contents/Resources"
cp "$ROOT_DIR/packaging/macos-Info.plist" "$APP_DIR/Contents/Info.plist"
cp "$ROOT_DIR/packaging/assets/bwih-dispatch.icns" "$APP_DIR/Contents/Resources/bwih-dispatch.icns"
cp "$ROOT_DIR/dist/BWIH Dispatch/BWIH Dispatch" "$APP_DIR/Contents/MacOS/BWIH Dispatch"
ditto "$ROOT_DIR/dist/BWIH Dispatch/_internal" "$APP_DIR/Contents/Frameworks"

# Remove macOS quarantine flag so the app can be shared without Gatekeeper blocking.
xattr -cr "$APP_DIR" 2>/dev/null || true

echo ""
echo "=== Build complete ==="
echo "App: $APP_DIR"
echo ""
echo "To distribute: zip the .app and share it."
echo "  cd release && zip -r BWIH-Dispatch-macOS.zip BWIH调度系统.app"
