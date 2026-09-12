import { useAgent, useCopilotKit } from "@copilotkit/react-native/headless";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Dimensions,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  ToastAndroid,
  View,
} from "react-native";
import { COPY, SYMPTOM_LABELS, type Action } from "@kinetic/ui-schema";
import { colors, radius } from "@kinetic/design-tokens";
import { useOverlayStore } from "../plan/overlay";
import { dispatchAction } from "../data/snapshot";
import { cancelInflight, probeWhisper, releaseWhisper, startRecording, transcribeFixture, transcribeRelease } from "./whisper";
import { useVoiceFixture } from "./fixture";

/**
 * VoiceLayer (§5.4 pipeline + workflows 07/08/11/12):
 *
 *   hold FAB → listening popover (wave · "Release to send" · privacy line ·
 *   typed-request field) → release → ON-DEVICE whisper transcription →
 *   transcript = message to the `router` agent → compose_overlay →
 *   result popover ("You said" + noted rows) →
 *   "Looks right" commits via typed Data API calls · "Say it again" re-records.
 *
 * Nothing commits before confirmation. STT needs no network; only the router
 * turn does (§5.4). If whisper can't initialise, the FAB hides and the typed
 * path stays available (deterministic guard).
 */

type Phase = "idle" | "listening" | "transcribing" | "classifying";

export default function VoiceLayer() {
  const { copilotkit } = useCopilotKit();
  const { agent: routerAgent, isReady: routerReady } = useAgent({ agentId: "router" });
  const overlay = useOverlayStore((s) => s.overlay);
  const clearOverlay = useOverlayStore((s) => s.clear);

  const [available, setAvailable] = useState<boolean | null>(null); // null = probing
  const [phase, setPhase] = useState<Phase>("idle");
  const [typed, setTyped] = useState("");
  const [micError, setMicError] = useState<string | null>(null);
  const turnRef = useRef<Promise<void>>(Promise.resolve());

  useEffect(() => {
    void probeWhisper().then(setAvailable);
  }, []);

  // §5.4 lifecycle: release the whisper context on background; the next
  // hold re-initialises lazily.
  useEffect(() => {
    const { AppState } = require("react-native") as typeof import("react-native");
    const sub = AppState.addEventListener("change", (s) => {
      if (s === "background") void releaseWhisper();
    });
    return () => sub.remove();
  }, []);

  // §5.5 dev harness: the ScenarioDrawer fixture button → same on-device
  // whisper transcribe → same router turn → same confirm-before-commit.
  // (Registered after routeTranscript below.)

  /** Send a transcript through the router (LLM classify → compose_overlay). */
  const routeTranscript = useCallback(
    async (transcript: string) => {
      setPhase("classifying");
      try {
        // v2 note: macrotask before the run, same as Home (§5.1 ledger).
        await new Promise((r) => setTimeout(r, 30));
        routerAgent.addMessage({ id: `voice-${Date.now()}`, role: "user", content: transcript });
        await copilotkit.runAgent({ agent: routerAgent });
      } catch (err) {
        console.warn("[voice] router run failed:", err);
        ToastAndroid.show("Couldn't reach the agent — try again", ToastAndroid.SHORT);
      } finally {
        setPhase("idle");
      }
    },
    [copilotkit, routerAgent],
  );

  // §5.5 dev harness registration (after routeTranscript exists).
  const routeRef = useRef(routeTranscript);
  routeRef.current = routeTranscript;
  useEffect(() => {
    useVoiceFixture.getState().register(async () => {
      setPhase("transcribing");
      try {
        const transcript = await transcribeFixture();
        clearOverlay();
        if (!transcript) {
          setMicError("Fixture produced no transcript.");
          setPhase("idle");
          return;
        }
        await routeRef.current(transcript);
      } catch (err) {
        console.warn("[voice] fixture failed:", err);
        setMicError(err instanceof Error ? err.message : "Fixture failed");
        setPhase("idle");
      }
    });
    return () => useVoiceFixture.getState().register(null);
  }, [clearOverlay]);

  const startTurn = useCallback(
    (typedText?: string) => {
      setMicError(null);
      const turn = (async () => {
        await turnRef.current; // serialize turns
        if (typedText !== undefined) {
          clearOverlay();
          await routeTranscript(typedText);
          return;
        }
        try {
          setPhase("listening");
          await startRecording();
        } catch (err) {
          console.warn("[voice] record start failed:", err);
          setMicError(err instanceof Error ? err.message : "Microphone failed");
          setPhase("idle");
        }
      })();
      turnRef.current = turn;
      void turn;
    },
    [clearOverlay, routeTranscript],
  );

  /** Release: stop → on-device transcribe → router (§5.4 step 2–3). */
  const endTurn = useCallback(() => {
    const turn = (async () => {
      await turnRef.current;
      try {
        setPhase("transcribing");
        const transcript = await transcribeRelease();
        if (!transcript) {
          setMicError("Nothing heard — hold the button and speak.");
          setPhase("idle");
          return;
        }
        clearOverlay();
        await routeTranscript(transcript);
      } catch (err) {
        console.warn("[voice] turn failed:", err);
        setMicError(err instanceof Error ? err.message : "Microphone failed");
        setPhase("idle");
      }
    })();
    turnRef.current = turn;
    void turn;
  }, [clearOverlay, routeTranscript]);

  const onPressIn = useCallback(() => {
    if (phase !== "idle") return;
    startTurn();
  }, [phase, startTurn]);

  // Hold-to-talk contract (§5.4): release ends the recording; the whisper
  // batch transcription + router turn run in the serialized turn promise.
  const onPressOut = useCallback(() => {
    if (phase === "listening") endTurn();
  }, [phase, endTurn]);

  const busy = phase === "transcribing" || phase === "classifying";

  return (
    <>
      {/* Result popover — the router's compose_overlay (§4.3) */}
      {overlay && <ResultPop onSayAgain={() => { clearOverlay(); startTurn(); }} />}

      {/* Listening popover (§5.4 stage A) */}
      {(phase === "listening" || busy) && !overlay && (
        <View style={[styles.pop, styles.listenPop]} pointerEvents="box-none">
          <Text style={styles.eyebrow}>{busy ? "One moment…" : COPY.listeningEyebrow}</Text>
          {phase === "listening" ? (
            <WaveBars />
          ) : (
            <ActivityIndicator color={colors.violet} style={styles.spinner} />
          )}
          <Text style={styles.privacy}>{busy ? "Checking what you said" : COPY.releaseToSend}</Text>
          <Text style={styles.privacyLine}>{COPY.privacyLine}</Text>
          {micError !== null && <Text style={styles.error}>{micError}</Text>}
        </View>
      )}

      {/* Mic FAB (66 px) — hidden entirely when STT can't init (§5.4 guard) */}
      {available !== false && (
        <View style={styles.fabWrap} pointerEvents="box-none">
          <Pressable
            style={[styles.fab, phase !== "idle" && styles.fabActive]}
            disabled={busy || routerReady !== true}
            onPressIn={onPressIn}
            onPressOut={onPressOut}
            onLongPress={onPressIn}
            delayLongPress={200}
          >
            <Text style={styles.fabText}>{phase === "idle" ? "Hold to talk" : "…"}</Text>
          </Pressable>
          <TypedRow
            value={typed}
            onChange={setTyped}
            disabled={busy}
            onSend={() => {
              const t = typed.trim();
              if (t) {
                setTyped("");
                startTurn(t);
              }
            }}
          />
        </View>
      )}
      {available === false && (
        <View style={styles.fabWrap} pointerEvents="box-none">
          <TypedRow
            value={typed}
            onChange={setTyped}
            disabled={busy}
            onSend={() => {
              const t = typed.trim();
              if (t) {
                setTyped("");
                startTurn(t);
              }
            }}
          />
        </View>
      )}
    </>
  );
}

function TypedRow({
  value,
  onChange,
  onSend,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  disabled: boolean;
}) {
  return (
    <View style={styles.typedRow}>
      <TextInput
        style={styles.typedInput}
        value={value}
        onChangeText={onChange}
        placeholder={COPY.typedRequestPlaceholder}
        placeholderTextColor={colors.chromeMuted}
        editable={!disabled}
        onSubmitEditing={onSend}
      />
      <Pressable style={[styles.sendBtn, disabled && styles.sendDisabled]} disabled={disabled} onPress={onSend}>
        <Text style={styles.sendText}>Send</Text>
      </Pressable>
    </View>
  );
}

/** Workflow-11 stage B: matched / unmatched, request verbatim under "You said". */
/** Workflow-07/08/12: noted rows + Change affordances (display-only in the demo). */
function ResultPop({ onSayAgain }: { onSayAgain: () => void }) {
  const overlay = useOverlayStore((s) => s.overlay);
  if (!overlay) return null;

  const confirmAction: Action | null = (() => {
    switch (overlay.variant) {
      case "sick": {
        const feeling = overlay.noted.find((n) => n.label === "Feeling")?.value ?? "";
        const labels = feeling
          .split(",")
          .map((s) => s.trim())
          .filter((l): l is (typeof SYMPTOM_LABELS)[number] => (SYMPTOM_LABELS as readonly string[]).includes(l));
        return labels.length > 0 ? { type: "log_symptoms", labels, transcript: overlay.said } : null;
      }
      case "health":
        return { type: "send_handoff", text: overlay.said };
      case "diary":
        return {
          type: "share_diary",
          text: overlay.said,
          noted: overlay.noted.flatMap((n) => (n.label === "Feeling" ? n.value.split(",").map((s) => s.trim()) : [])),
        };
      case "command_unmatched":
        // Workflow-11 §4-4: the request itself becomes the handoff.
        return { type: "send_handoff", text: `Please add a workflow for: “${overlay.said}”` };
      default:
        return null; // dose/command_matched are UI-local below
    }
  })();

  const confirmLabel =
    overlay.variant === "command_unmatched" ? "Ask my care team" : COPY.looksRight;

  const onConfirm = () => {
    if (confirmAction) dispatchAction(confirmAction);
    if (overlay.variant === "command_matched" && overlay.workflow) {
      ToastAndroid.show(`Workflow → ${overlay.workflow}`, ToastAndroid.SHORT);
    }
    if (overlay.variant === "dose") {
      ToastAndroid.show("Use the dose card chips to log your dose", ToastAndroid.SHORT);
    }
    useOverlayStore.getState().clear();
  };

  return (
    <View style={[styles.pop, styles.resultPop]}>
      <Text style={styles.eyebrow}>{COPY.youSaidEyebrow}</Text>
      <Text style={styles.quote}>“{overlay.said}”</Text>
      {overlay.noted.length > 0 && <Text style={styles.eyebrowDark}>{COPY.notedEyebrow}</Text>}
      {overlay.noted.map((n) => (
        <View key={`${n.label}-${n.value}`} style={styles.notedRow}>
          <Text style={styles.notedLabel}>{n.label}</Text>
          <Text style={styles.notedValue} numberOfLines={2}>
            {n.value}
          </Text>
          {n.changeable && <Text style={styles.change}>Change</Text>}
        </View>
      ))}
      {overlay.variant === "command_matched" && (
        <Text style={styles.willDo}>Here's what I'll do → {overlay.workflow}</Text>
      )}
      {overlay.variant === "command_unmatched" && (
        <Text style={styles.willDo}>No workflow for that yet. I can ask your care team to add one.</Text>
      )}
      <View style={styles.popButtons}>
        <Pressable style={styles.primary} onPress={onConfirm}>
          <Text style={styles.primaryText}>{confirmLabel}</Text>
        </Pressable>
        <Pressable style={styles.ghost} onPress={onSayAgain}>
          <Text style={styles.ghostText}>{COPY.sayItAgain}</Text>
        </Pressable>
      </View>
    </View>
  );
}

function WaveBars() {
  const heights = [10, 18, 26, 34, 26, 18, 10, 16, 24, 30, 22, 14, 8, 18, 28, 34, 24, 12];
  return (
    <View style={styles.wave}>
      {heights.map((h, i) => (
        <View key={i} style={[styles.waveBar, { height: h, opacity: 0.45 + (h / 34) * 0.55 }]} />
      ))}
    </View>
  );
}

const { width } = Dimensions.get("window");

const styles = StyleSheet.create({
  fabWrap: {
    position: "absolute",
    left: 16,
    right: 16,
    bottom: 18,
    alignItems: "center",
    gap: 8,
  },
  fab: {
    width: 66,
    height: 66,
    borderRadius: 33,
    backgroundColor: colors.btn,
    alignItems: "center",
    justifyContent: "center",
    elevation: 4,
  },
  fabActive: { backgroundColor: colors.violet },
  fabText: { color: colors.btnInk, fontSize: 11, fontWeight: "800" },
  typedRow: { flexDirection: "row", gap: 8, width: "100%" },
  typedInput: {
    flex: 1,
    backgroundColor: colors.surface,
    borderColor: colors.line,
    borderWidth: 1,
    borderRadius: radius.chip,
    paddingHorizontal: 14,
    minHeight: 44,
    color: colors.ink,
    fontSize: 13,
  },
  sendBtn: {
    backgroundColor: colors.cyan,
    borderRadius: radius.chip,
    paddingHorizontal: 18,
    minHeight: 44,
    justifyContent: "center",
  },
  sendDisabled: { opacity: 0.5 },
  sendText: { color: colors.btnInk, fontSize: 13, fontWeight: "800" },
  pop: {
    position: "absolute",
    right: 16,
    width: Math.min(320, width - 32),
    backgroundColor: colors.surface,
    borderColor: colors.line,
    borderWidth: 1,
    borderRadius: 24,
    padding: 16,
    gap: 8,
    elevation: 8,
  },
  listenPop: { bottom: 104 },
  resultPop: { bottom: 104 },
  eyebrow: { color: colors.violet, fontSize: 11, fontWeight: "800", textTransform: "uppercase" },
  eyebrowDark: { color: colors.muted, fontSize: 11, fontWeight: "800", textTransform: "uppercase", marginTop: 4 },
  wave: { flexDirection: "row", alignItems: "center", gap: 3, height: 36 },
  waveBar: { width: 4, borderRadius: 2, backgroundColor: colors.violet },
  spinner: { height: 36 },
  privacy: { color: colors.ink, fontSize: 13, fontWeight: "700" },
  privacyLine: { color: colors.muted, fontSize: 11 },
  error: { color: "#B3402E", fontSize: 11 },
  quote: { color: colors.ink, fontSize: 15, lineHeight: 21, fontWeight: "600" },
  notedRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  notedLabel: { color: colors.muted, fontSize: 12, width: 76 },
  notedValue: { color: colors.ink, fontSize: 13, fontWeight: "700", flexShrink: 1, flex: 1 },
  change: { color: colors.violet, fontSize: 12, fontWeight: "700" },
  willDo: { color: colors.ink, fontSize: 13, fontWeight: "600" },
  popButtons: { flexDirection: "row", gap: 8, marginTop: 4 },
  primary: {
    backgroundColor: colors.btn,
    borderRadius: radius.chip,
    paddingHorizontal: 16,
    paddingVertical: 12,
    minHeight: 44,
    justifyContent: "center",
    flexGrow: 1,
  },
  primaryText: { color: colors.btnInk, fontSize: 13, fontWeight: "800", textAlign: "center" },
  ghost: {
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: radius.chip,
    paddingHorizontal: 16,
    paddingVertical: 12,
    minHeight: 44,
    justifyContent: "center",
  },
  ghostText: { color: colors.ink, fontSize: 13, fontWeight: "700", textAlign: "center" },
});
