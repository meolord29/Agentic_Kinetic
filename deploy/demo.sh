#!/usr/bin/env bash
# deploy/demo.sh — single-box demo bootstrap (architecture §9.0).
# Self-contained: exports ANDROID_HOME/PATH itself, never relies on the caller's shell.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Android/Sdk}"
export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"

AVD_NAME="${AVD_NAME:-kinetic}"
APK="${APK:-$REPO_ROOT/apps/mobile/android/app/build/outputs/apk/release/app-release.apk}"

echo "== 1/5 backend compose up =="
docker compose --env-file "$REPO_ROOT/deploy/.env" -f "$REPO_ROOT/deploy/docker-compose.yml" up --build -d --wait
curl -fsS http://localhost:8080/healthz >/dev/null && echo "data-api /healthz green"
curl -fsS http://localhost:8200/healthz >/dev/null && echo "runtime  /healthz green"

echo "== 2/5 adb daemon (first-boot rule: adb before emulator) =="
adb devices

echo "== 3/5 emulator boot =="
if ! adb devices | grep -q "emulator-"; then
  emulator -avd "$AVD_NAME" -no-metrics &
  adb wait-for-device
  # wait for full boot
  until [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; do sleep 2; done
fi
adb devices

echo "== 4/5 install .apk =="
adb install -r "$APK"
adb shell monkey -p ai.kinetic.patient -c android.intent.category.LAUNCHER 1

echo "== 5/5 verify =="
sleep 3
adb exec-out screencap -p > "$REPO_ROOT/deploy/demo-screencap.png"
echo "screencap: $REPO_ROOT/deploy/demo-screencap.png"
adb logcat -d -s ReactNativeJS:E || true
echo "demo up: app → http://10.0.2.2:8200/api/copilotkit"
