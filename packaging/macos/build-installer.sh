#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPOSITORY_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VERSION="${1:-${WIFI_AGENT_VERSION:-}}"

cd "$REPOSITORY_ROOT"
if [[ -z "$VERSION" ]]; then
    VERSION="$($PYTHON_BIN -c 'import wifi_agent; print(wifi_agent.APP_VERSION)')"
fi

BUILD_ROOT="$REPOSITORY_ROOT/build/macos"
ASSET_DIRECTORY="$BUILD_ROOT/assets"
OUTPUT_DIRECTORY="$BUILD_ROOT/installer"
APP_PATH="$BUILD_ROOT/dist/WiFi Agent.app"
ARCHITECTURE="$(uname -m)"
ARTIFACT_STEM="WiFiAgent-$VERSION-macOS-$ARCHITECTURE"

rm -rf "$BUILD_ROOT"
mkdir -p "$ASSET_DIRECTORY" "$OUTPUT_DIRECTORY"

"$PYTHON_BIN" packaging/generate_assets.py --version "$VERSION" --output-dir "$ASSET_DIRECTORY"

PYINSTALLER_ARGUMENTS=(
    --noconfirm
    --clean
    --windowed
    --onedir
    --name "WiFi Agent"
    --icon "$ASSET_DIRECTORY/wifi-agent.icns"
    --osx-bundle-identifier "com.akshajtiwari.wifiagent"
    --target-architecture "$ARCHITECTURE"
    --paths "$ASSET_DIRECTORY"
    --collect-submodules keyring.backends
    --hidden-import pystray._darwin
    --distpath "$BUILD_ROOT/dist"
    --workpath "$BUILD_ROOT/work"
    --specpath "$BUILD_ROOT/spec"
)
if [[ -n "${MACOS_APP_SIGNING_IDENTITY:-}" ]]; then
    PYINSTALLER_ARGUMENTS+=(--codesign-identity "$MACOS_APP_SIGNING_IDENTITY")
fi
"$PYTHON_BIN" -m PyInstaller "${PYINSTALLER_ARGUMENTS[@]}" wifi_agent.py

/usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string $VERSION" "$APP_PATH/Contents/Info.plist" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$APP_PATH/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $VERSION" "$APP_PATH/Contents/Info.plist" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Set :CFBundleVersion $VERSION" "$APP_PATH/Contents/Info.plist"

if [[ -n "${MACOS_APP_SIGNING_IDENTITY:-}" ]]; then
    codesign --force --options runtime --timestamp --sign "$MACOS_APP_SIGNING_IDENTITY" "$APP_PATH"
else
    codesign --force --options runtime --sign - "$APP_PATH"
fi
codesign --verify --deep --strict --verbose=2 "$APP_PATH"

PACKAGE_PATH="$OUTPUT_DIRECTORY/$ARTIFACT_STEM.pkg"
PACKAGE_PAYLOAD="$BUILD_ROOT/package-payload"
COMPONENT_PACKAGE="$BUILD_ROOT/WiFiAgent-component.pkg"
mkdir -p "$PACKAGE_PAYLOAD/Applications"
ditto "$APP_PATH" "$PACKAGE_PAYLOAD/Applications/WiFi Agent.app"
pkgbuild \
    --root "$PACKAGE_PAYLOAD" \
    --identifier "com.akshajtiwari.wifiagent" \
    --version "$VERSION" \
    --install-location / \
    --scripts "$SCRIPT_DIR/scripts" \
    "$COMPONENT_PACKAGE"

PRODUCTBUILD_ARGUMENTS=(--package "$COMPONENT_PACKAGE")
if [[ -n "${MACOS_INSTALLER_SIGNING_IDENTITY:-}" ]]; then
    PRODUCTBUILD_ARGUMENTS+=(--sign "$MACOS_INSTALLER_SIGNING_IDENTITY")
fi
productbuild "${PRODUCTBUILD_ARGUMENTS[@]}" "$PACKAGE_PATH"

DMG_STAGE="$BUILD_ROOT/dmg"
mkdir -p "$DMG_STAGE"
ditto "$APP_PATH" "$DMG_STAGE/WiFi Agent.app"
ln -s /Applications "$DMG_STAGE/Applications"
DMG_PATH="$OUTPUT_DIRECTORY/$ARTIFACT_STEM.dmg"
hdiutil create -volname "WiFi Agent" -srcfolder "$DMG_STAGE" -ov -format UDZO "$DMG_PATH"
if [[ -n "${MACOS_APP_SIGNING_IDENTITY:-}" ]]; then
    codesign --force --timestamp --sign "$MACOS_APP_SIGNING_IDENTITY" "$DMG_PATH"
fi

if [[ -n "${APPLE_NOTARY_KEYCHAIN_PROFILE:-}" ]]; then
    for artifact in "$PACKAGE_PATH" "$DMG_PATH"; do
        xcrun notarytool submit "$artifact" --keychain-profile "$APPLE_NOTARY_KEYCHAIN_PROFILE" --wait
        xcrun stapler staple "$artifact"
    done
fi

echo "macOS installers created in $OUTPUT_DIRECTORY"
