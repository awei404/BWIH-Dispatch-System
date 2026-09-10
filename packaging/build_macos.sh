#!/bin/zsh
set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

export PYINSTALLER_CONFIG_DIR="$ROOT_DIR/build/pyinstaller-cache-$(date +%s)"
mkdir -p "$PYINSTALLER_CONFIG_DIR"

python3 -m PyInstaller --noconfirm --clean "$ROOT_DIR/BWIH调度系统.spec"

APP_DIR="$ROOT_DIR/release/BWIH调度系统.app"
rm -rf "$APP_DIR"
mkdir -p "$ROOT_DIR/release"
ditto "$ROOT_DIR/dist/BWIH调度系统.app" "$APP_DIR"
cp "$ROOT_DIR/packaging/macos-Info.plist" "$APP_DIR/Contents/Info.plist"

# Re-sign after applying the final bundle metadata; otherwise macOS treats the
# changed Info.plist as a damaged application.
codesign --force --deep --sign - "$APP_DIR"

# Remove macOS quarantine flag so the app can be shared without Gatekeeper blocking.
xattr -cr "$APP_DIR" 2>/dev/null || true

echo ""
echo "=== Build complete ==="
echo "App: $APP_DIR"
echo ""
echo "To distribute: zip the .app and share it."
echo "  cd release && zip -r BWIH-Dispatch-macOS.zip BWIH调度系统.app"
