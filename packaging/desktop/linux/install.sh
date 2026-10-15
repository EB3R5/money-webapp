#!/usr/bin/env bash
# Install the Linux desktop entry for money-webapp (Debian/Ubuntu).
#   1. checks the apt packages pywebview's GTK backend needs
#   2. exposes the system `gi` module to the repo .venv via a .pth file
#   3. renders money.desktop with this repo's path and installs it + the icon
# Usage: packaging/desktop/linux/install.sh      (re-runnable)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
APP=money

missing=()
for pkg in python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1; do
  dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
done
if ((${#missing[@]})); then
  echo "missing apt packages: ${missing[*]}" >&2
  echo "  sudo apt install ${missing[*]}" >&2
  exit 1
fi

[ -x "$REPO/.venv/bin/python" ] || { echo "no .venv in $REPO — python -m venv .venv && pip install -e '.[desktop]'" >&2; exit 1; }
SITE="$("$REPO/.venv/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
echo "/usr/lib/python3/dist-packages" > "$SITE/system-gi.pth"

mkdir -p ~/.local/share/applications ~/.local/share/icons/hicolor/256x256/apps
sed "s|@@REPO@@|$REPO|g" "$HERE/$APP.desktop" > ~/.local/share/applications/$APP.desktop
cp "$HERE/$APP.png" ~/.local/share/icons/hicolor/256x256/apps/$APP.png
command -v update-desktop-database >/dev/null && update-desktop-database ~/.local/share/applications || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q ~/.local/share/icons/hicolor || true
echo "installed ~/.local/share/applications/$APP.desktop -> $REPO"
