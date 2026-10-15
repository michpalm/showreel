#!/usr/bin/env bash
# Build the plugin and package it for Decky's "Install plugin from ZIP/URL". Usage: scripts/package.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
pnpm build
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
PKG="$STAGE/showreel"
mkdir -p "$PKG/py_modules" out
cp plugin.json package.json main.py LICENSE "$PKG/"
cp -R dist "$PKG/dist"
rm -f "$PKG"/dist/*.map
cp -R py_modules/showreel "$PKG/py_modules/showreel"
find "$PKG" -name '__pycache__' -prune -exec rm -rf {} +
rm -f out/showreel.zip
(cd "$STAGE" && zip -qr "$ROOT/out/showreel.zip" showreel)
unzip -l out/showreel.zip
