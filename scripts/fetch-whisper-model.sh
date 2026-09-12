#!/usr/bin/env bash
# scripts/fetch-whisper-model.sh — fetch the whisper.cpp model (§5.4) into
# apps/mobile/assets/whisper/ so Metro bundles it into the APK.
# User decision P4: ggml-tiny multilingual f16 (~75 MB) — APK-halving swap
# from the doc's ggml-base (~148 MB); accuracy tradeoff accepted for the demo.
# Gitignored (too big for the repo); demo.sh runs this on first boot.
set -euo pipefail

DEST="$(dirname "$0")/../apps/mobile/assets/whisper"
URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin"
FILE="$DEST/ggml-tiny.bin"

mkdir -p "$DEST"

# Drop superseded models so the APK only ever carries one.
rm -f "$DEST"/ggml-base.bin "$DEST"/ggml-base.bin.part

if [ -f "$FILE" ]; then
  echo "fetch-whisper-model: $FILE already present ($(du -h "$FILE" | cut -f1))"
  exit 0
fi

echo "fetch-whisper-model: downloading ggml-tiny f16 (~75 MB)…"
curl -fL --retry 3 -o "$FILE.part" "$URL"
mv "$FILE.part" "$FILE"
echo "fetch-whisper-model: done ($(du -h "$FILE" | cut -f1)) → $FILE"
