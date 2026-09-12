#!/usr/bin/env bash
# scripts/fetch-whisper-model.sh — fetch the ggml-base f16 model (§5.4, ~148 MB)
# into apps/mobile/assets/whisper/ so Metro bundles it into the APK.
# Gitignored (too big for the repo); demo.sh runs this on first boot.
set -euo pipefail

DEST="$(dirname "$0")/../apps/mobile/assets/whisper"
URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"
FILE="$DEST/ggml-base.bin"

mkdir -p "$DEST"

if [ -f "$FILE" ]; then
  echo "fetch-whisper-model: $FILE already present ($(du -h "$FILE" | cut -f1))"
  exit 0
fi

echo "fetch-whisper-model: downloading ggml-base f16 (~148 MB)…"
curl -fL --retry 3 -o "$FILE.part" "$URL"
mv "$FILE.part" "$FILE"
echo "fetch-whisper-model: done ($(du -h "$FILE" | cut -f1)) → $FILE"
