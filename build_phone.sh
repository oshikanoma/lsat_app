#!/bin/bash
# Reproducible end-to-end Android build for homebase.
#
# One command turns the current source tree into an installable APK, so the
# phone build is verifiable evidence rather than a manual sequence:
#   1. builds the SvelteKit UI bundle,
#   2. copies it into the Android app's assets (+ native bridge shim),
#   3. compiles the APK against this fork's shared Rust engine,
#   4. prints the artifact path, size and SHA-256 for verification.
#
# Prereqs (one-time): JDK 17, Android SDK + NDK, cargo-ndk and the Android Rust
# targets. All paths are captured in mobile-env.sh, which this script sources.
#
# Usage:
#   ./build_phone.sh              # full (Full) debug APK
#   ABI=arm64-v8a ./build_phone.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
ABI="${ABI:-arm64-v8a}"

# shellcheck disable=SC1091
source "$ROOT/mobile-env.sh"

echo "==> [1/3] Building SvelteKit UI bundle"
"$ROOT/ninja" sveltekit

echo "==> [2/3] Syncing web bundle into Android assets"
"$ROOT/sync_lsat_web.sh"

echo "==> [3/3] Assembling APK (this compiles the shared Rust engine for $ABI)"
cd "$MOBILE_DIR/Anki-Android"
./gradlew :AnkiDroid:assembleFullDebug

APK="AnkiDroid/build/outputs/apk/full/debug/AnkiDroid-full-${ABI}-debug.apk"
if [ ! -f "$APK" ]; then
  echo "error: expected APK not found at $APK" >&2
  echo "Available APKs:" >&2
  ls -1 AnkiDroid/build/outputs/apk/full/debug/*.apk >&2 || true
  exit 1
fi

FULL_APK="$MOBILE_DIR/Anki-Android/$APK"
echo
echo "==> Build succeeded. Artifact evidence:"
echo "    path:   $FULL_APK"
echo "    size:   $(du -h "$FULL_APK" | cut -f1)"
echo "    sha256: $(shasum -a 256 "$FULL_APK" | cut -d' ' -f1)"
echo
echo "Install onto a connected device/emulator with:"
echo "    adb install -r -d \"$FULL_APK\""
