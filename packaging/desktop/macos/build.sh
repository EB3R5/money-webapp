#!/bin/zsh
# Build /Applications/money.app from scratch.
# Usage: packaging/desktop/macos/build.sh
# Requires: Xcode CLT (clang), repo .venv with the desktop extra (pip install -e ".[desktop]").
set -euo pipefail

HERE="${0:A:h}"
REPO="${HERE:h:h:h}"
APP="/Applications/money.app"
BUNDLE_ID="${MONEY_BUNDLE_ID:-local.money-webapp.desktop}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "== compile launcher =="
clang -O2 -DMONEY_REPO="\"$REPO\"" -o "$TMP/money" "$HERE/launcher.c"

echo "== icon =="
"$REPO/.venv/bin/python" "$HERE/make_icon.py" "$TMP/icon_1024.png"
ICONSET="$TMP/money.iconset"
mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s "$TMP/icon_1024.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2))
  sips -z $d $d "$TMP/icon_1024.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$TMP/money.icns"

echo "== assemble bundle =="
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$TMP/money" "$APP/Contents/MacOS/money"
cp "$TMP/money.icns" "$APP/Contents/Resources/money.icns"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>money</string>
  <key>CFBundleDisplayName</key><string>money</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleVersion</key><string>0.1.0</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>money</string>
  <key>CFBundleIconFile</key><string>money</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

echo "== sign + register =="
codesign --force -s - --identifier "$BUNDLE_ID" "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP"

echo "done: $APP"
echo "First launch: approve the macOS prompt to access the Documents folder."
