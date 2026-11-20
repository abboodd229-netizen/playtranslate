#!/bin/bash
# Fetches the Remote Play code (Pylux, an open-source fork of Chiaki, AGPL-3.0) at a pinned
# commit into third_party/pylux, then applies PlayTranslate's small patches to it.
# Nothing from Pylux is committed to this repository; CI runs this script on every build.
set -euo pipefail

PYLUX_REPO="https://github.com/ForWard-Technologies-LLC/Pylux.git"
PYLUX_COMMIT="ca87a49a12bab071948f565ca53ffdad790775d3"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$HERE/third_party/pylux"

if [ -d "$DEST/.git" ] && [ "$(git -C "$DEST" rev-parse HEAD)" = "$PYLUX_COMMIT" ] \
   && [ -f "$DEST/.playtranslate-patched" ]; then
    echo "Pylux $PYLUX_COMMIT already fetched and patched."
    exit 0
fi

rm -rf "$DEST"
mkdir -p "$DEST"
git -C "$DEST" init -q
git -C "$DEST" remote add origin "$PYLUX_REPO"
git -C "$DEST" fetch -q --depth 1 origin "$PYLUX_COMMIT"
git -C "$DEST" checkout -q FETCH_HEAD
# Only the submodules the iOS library needs.
git -C "$DEST" submodule update --init --depth 1 \
    third-party/nanopb third-party/jerasure third-party/gf-complete third-party/curl

python3 "$HERE/scripts/patch-pylux.py" "$DEST"
touch "$DEST/.playtranslate-patched"
echo "Pylux $PYLUX_COMMIT fetched and patched into $DEST"
