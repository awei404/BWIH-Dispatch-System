#!/bin/zsh
set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_SOURCE="$ROOT_DIR/release/BWIH调度系统.app"
STAGING_DIR="$ROOT_DIR/build/macos-dmg-staging"
DMG_PATH="$ROOT_DIR/release/BWIH-Dispatch-macOS-Apple-Silicon.dmg"

if [ ! -d "$APP_SOURCE" ]; then
    zsh "$ROOT_DIR/packaging/build_macos.sh"
fi

rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"
ditto "$APP_SOURCE" "$STAGING_DIR/BWIH Dispatch.app"
cp "$ROOT_DIR/packaging/macOS使用说明.txt" "$STAGING_DIR/使用说明.txt"
ln -s /Applications "$STAGING_DIR/Applications"

rm -f "$DMG_PATH"
hdiutil create \
    -volname "BWIH Dispatch" \
    -srcfolder "$STAGING_DIR" \
    -ov \
    -format UDZO \
    "$DMG_PATH"

echo ""
echo "=== DMG complete ==="
echo "Installer: $DMG_PATH"
