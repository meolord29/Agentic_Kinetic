import { Platform } from "react-native";
import { initWhisper, type WhisperContext } from "whisper.rn";
import * as FileSystem from "expo-file-system/legacy";
import AudioRecord from "react-native-audio-record";

/**
 * whisper.rn context lifecycle (§5.4) — STT runs ENTIRELY on-device:
 *
 *   press FAB → startRecording()   (mono 16 kHz 16-bit PCM → WAV, cache dir)
 *   release   → transcribeRelease()→ context.transcribe(wav) → WAV deleted
 *                                  → only the transcript persists
 *
 * The context is lazily initialised on the first hold-to-talk (avoids startup
 * cost); in-flight transcribes are cancellable for "Say it again". The
 * ggml-tiny model is bundled in the APK (metro assetExts "bin"; fetch once
 * with scripts/fetch-whisper-model.sh).
 */

// Metro turns the require into an asset number; whisper.rn resolves its path.
// If the model file is missing from assets this require still succeeds — the
// init call is what fails, and the FAB hides (deterministic guard below).
// User decision P4: ggml-tiny multilingual f16 (~75 MB) instead of base —
// demo clips are short; accuracy tradeoff accepted, APK halves.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const MODEL_ASSET = require("../../assets/whisper/ggml-tiny.bin");
// §5.5 dev harness: bundled fixture clip ("I have a flu", 16 kHz mono WAV).
// Same on-device whisper context as the mic path — only the recorder differs.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const FLU_FIXTURE = require("../../assets/voice/demo-flu.wav");

const WAV_FILE = "tap-to-talk.wav";
const LANGUAGE = "en";

let context: WhisperContext | null = null;
let initPromise: Promise<WhisperContext> | null = null;
let inflight: { stop: () => Promise<void> } | null = null;
let recording = false;

async function getContext(): Promise<WhisperContext> {
  if (context) return context;
  if (!initPromise) {
    initPromise = initWhisper({ filePath: MODEL_ASSET, isBundleAsset: true })
      .then((ctx) => {
        context = ctx;
        return ctx;
      })
      .catch((err) => {
        initPromise = null; // one context re-init retry per §5.4 failure table
        throw err;
      });
  }
  return initPromise;
}

/** Release on background (§5.4 lifecycle). Safe to call repeatedly. */
export async function releaseWhisper(): Promise<void> {
  recording = false;
  await cancelInflight();
  const ctx = context;
  context = null;
  initPromise = null;
  if (ctx) await ctx.release().catch(() => {});
}

export async function cancelInflight(): Promise<void> {
  if (!inflight) return;
  const t = inflight;
  inflight = null;
  try {
    await t.stop();
  } catch {
    // already finished
  }
}

/** Press: lazily init the context (first-hold cost) then start recording. */
export async function startRecording(): Promise<void> {
  await getContext();
  AudioRecord.init({
    sampleRate: 16000,
    channels: 1,
    bitsPerSample: 16,
    wavFile: WAV_FILE,
    audioSource: Platform.OS === "android" ? 6 : undefined, // 6 = VOICE_RECOGNITION
  });
  recording = true;
  AudioRecord.start();
}

/**
 * Release: stop the recorder, transcribe the WAV on-device, delete the WAV
 * immediately (§5.4). Resolves with the verbatim transcript.
 */
export async function transcribeRelease(): Promise<string> {
  if (!recording) throw new Error("not recording");
  recording = false;
  const wavPath = await AudioRecord.stop();

  const ctx = await getContext();
  const t = ctx.transcribe(wavPath, { language: LANGUAGE });
  inflight = t;
  try {
    const result = await t.promise;
    return (result.result ?? "").trim();
  } finally {
    inflight = null;
    // §5.4: WAV deleted immediately; only the transcript persists.
    await FileSystem.deleteAsync(wavPath, { idempotent: true }).catch(() => {});
  }
}

/**
 * Dev harness (§5.5): transcribe the bundled fixture WAV through the same
 * on-device context the mic path uses. Proves the whisper.cpp → router →
 * compose_overlay loop without host-mic passthrough (and offline).
 */
export async function transcribeFixture(): Promise<string> {
  const ctx = await getContext();
  const t = ctx.transcribe(FLU_FIXTURE, { language: LANGUAGE });
  inflight = t;
  try {
    const result = await t.promise;
    return (result.result ?? "").trim();
  } finally {
    inflight = null;
  }
}

/**
 * Deterministic guard (§5.4 failure table): probe whether STT can initialise.
 * On failure the caller hides the mic FAB — the typed-request path remains.
 * One retry, then permanent fallback for this session.
 */
export async function probeWhisper(): Promise<boolean> {
  try {
    await getContext();
    return true;
  } catch {
    try {
      await getContext();
      return true;
    } catch (err) {
      console.warn("[whisper] unavailable — typed input only:", err instanceof Error ? err.message : err);
      return false;
    }
  }
}
