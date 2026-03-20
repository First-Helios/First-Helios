#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# SpiritPool — Cross-Browser Build Script
#
# Produces platform-specific extension packages under dist/:
#   dist/firefox/   — Firefox MV3 (original, uses browser.* natively)
#   dist/chrome/    — Chrome MV3  (service_worker + polyfill)
#   dist/safari/    — Safari MV3  (same as Chrome; feed to converter)
#
# Usage:
#   ./build.sh              # build all targets
#   ./build.sh firefox      # build only Firefox
#   ./build.sh chrome       # build only Chrome
#   ./build.sh safari       # build only Safari
#
# After building Safari, generate the Xcode project with:
#   xcrun safari-web-extension-converter dist/safari/ \
#       --project-location spiritpool-safari-xcode --app-name SpiritPool
# ──────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST="$SCRIPT_DIR/dist"

# Shared source directories/files to copy into every target
SHARED_DIRS=(content shared popup options icons compat)
SHARED_FILES=(shared/selectors.json)

# ── Helpers ──────────────────────────────────────────────────

copy_shared() {
  local dest="$1"
  for dir in "${SHARED_DIRS[@]}"; do
    if [[ -d "$SCRIPT_DIR/$dir" ]]; then
      cp -R "$SCRIPT_DIR/$dir" "$dest/$dir"
    fi
  done
  # Copy any loose shared files that live outside directories
  for f in "${SHARED_FILES[@]}"; do
    if [[ -f "$SCRIPT_DIR/$f" ]]; then
      mkdir -p "$dest/$(dirname "$f")"
      cp "$SCRIPT_DIR/$f" "$dest/$f"
    fi
  done
}

# ── Firefox Build ────────────────────────────────────────────

build_firefox() {
  echo "🦊 Building Firefox extension…"
  local out="$DIST/firefox"
  rm -rf "$out" && mkdir -p "$out"

  copy_shared "$out"

  # Background script — straight copy (Firefox supports browser.* natively)
  cp "$SCRIPT_DIR/background.js" "$out/background.js"

  # Firefox manifest — use the original
  cp "$SCRIPT_DIR/manifest.json" "$out/manifest.json"

  echo "   → $out"
}

# ── Chrome Build ─────────────────────────────────────────────

build_chrome() {
  echo "🌐 Building Chrome extension…"
  local out="$DIST/chrome"
  rm -rf "$out" && mkdir -p "$out"

  copy_shared "$out"

  # Background service worker — prepend polyfill so browser.* is defined
  # before any code in background.js runs.
  {
    cat "$SCRIPT_DIR/compat/browser-polyfill.js"
    echo ""
    echo "// ── Original background.js ────────────────────────────────"
    cat "$SCRIPT_DIR/background.js"
  } > "$out/background.js"

  # Chrome manifest
  cp "$SCRIPT_DIR/manifest.chrome.json" "$out/manifest.json"

  echo "   → $out"
}

# ── Safari Build ─────────────────────────────────────────────

build_safari() {
  echo "🧭 Building Safari extension…"
  local out="$DIST/safari"
  rm -rf "$out" && mkdir -p "$out"

  copy_shared "$out"

  # Background service worker — same polyfill approach as Chrome
  {
    cat "$SCRIPT_DIR/compat/browser-polyfill.js"
    echo ""
    echo "// ── Original background.js ────────────────────────────────"
    cat "$SCRIPT_DIR/background.js"
  } > "$out/background.js"

  # Safari manifest
  cp "$SCRIPT_DIR/manifest.safari.json" "$out/manifest.json"

  echo "   → $out"
  echo ""
  echo "   To generate the Xcode project:"
  echo "   xcrun safari-web-extension-converter $out \\"
  echo "       --project-location spiritpool-safari-xcode --app-name SpiritPool"
}

# ── Main ─────────────────────────────────────────────────────

target="${1:-all}"

case "$target" in
  firefox) build_firefox ;;
  chrome)  build_chrome  ;;
  safari)  build_safari  ;;
  all)
    build_firefox
    build_chrome
    build_safari
    echo ""
    echo "✅ All targets built in $DIST/"
    ;;
  *)
    echo "Usage: $0 [firefox|chrome|safari|all]"
    exit 1
    ;;
esac
