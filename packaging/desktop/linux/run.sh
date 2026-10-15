#!/usr/bin/env bash
# Launch money-webapp as a native desktop window (pywebview + GTK/WebKit2).
#
# The .venv runs its own Python, so it can't see the system PyGObject (`gi`) or
# the GObject-introspection typelibs unless we point at them explicitly. Both are
# provided by the apt packages python3-gi / gir1.2-gtk-3.0 / gir1.2-webkit2-4.1.
#
# `gi` itself is exposed to the venv via .venv/.../site-packages/system-gi.pth
# (written by install.sh), which *appends* /usr/lib/python3/dist-packages to
# sys.path so the venv's own packages still win. We only need the typelib path here.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO"

export GI_TYPELIB_PATH="/usr/lib/x86_64-linux-gnu/girepository-1.0${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"

exec ./.venv/bin/python packaging/desktop/launcher.py
