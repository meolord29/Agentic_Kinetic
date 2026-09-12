import { useAgent, useCopilotKit } from "@copilotkit/react-native/headless";
import { useCallback, useEffect, useRef, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, ToastAndroid, View, useWindowDimensions } from "react-native";
import { colors, grid, radius, toneBackground, toneBorder } from "@kinetic/design-tokens";
import type { Action, HomePlan, Tile } from "@kinetic/ui-schema";
import { usePlanStore } from "../plan/store";
import { dispatchAction, useSnapshotLifecycle, useSnapshotStore } from "../data/snapshot";

type RunState = "idle" | "running" | "ok" | "error";

/**
 * P1 probe screen: the §4.7 plan loop, end to end —
 *   chip tap → dispatchAction (optimistic + §5.6 queue) → runAgent
 *   → compose_home → ui-schema gate → commit → bento re-render.
 * The full 17-component registry is P2 — tiles render as tone-tinted cards.
 */
export default function ProbeHome() {
  useSnapshotLifecycle();

  const { copilotkit } = useCopilotKit();
  const { agent, isReady } = useAgent({ agentId: "ui_agent" });
  const plan = usePlanStore((s) => s.plan);
  const committedAt = usePlanStore((s) => s.committedAt);
  const parseError = usePlanStore((s) => s.parseError);
  const connectivity = useSnapshotStore((s) => s.connectivity);
  const queued = useSnapshotStore((s) => s.queued);
  const planNonce = useSnapshotStore((s) => s.planNonce);
  const [runState, setRunState] = useState<RunState>("idle");
  const [runMs, setRunMs] = useState<number | null>(null);
  const [runs, setRuns] = useState(0);

  const run = useCallback(async () => {
    setRunState("running");
    const t0 = Date.now();
    try {
      // v2 note: yield a macrotask so a just-registered agent context commits
      // before the run reads it (CopilotKitRN ledger §5.1).
      await new Promise((r) => setTimeout(r, 30));
      console.log("[run] start");
      await copilotkit.runAgent({ agent });
      setRunMs(Date.now() - t0);
      setRuns((n) => n + 1);
      setRunState("ok");
      console.log("[run] ok", Date.now() - t0, "ms");
    } catch (err) {
      setRunState("error");
      console.warn("[probe] runAgent failed:", err);
    }
  }, [copilotkit, agent]);

  const runRef = useRef(run);
  runRef.current = run;

  useEffect(() => {
    if (isReady) void runRef.current();
  }, [isReady, planNonce]);

  const onChip = useCallback((action: Action) => {
    console.log("[action]", JSON.stringify(action));
    ToastAndroid.show(JSON.stringify(action), ToastAndroid.SHORT);
    dispatchAction(action);
  }, []);

  const statusLine =
    connectivity === "online"
      ? `ui_agent · ${runState}${runMs !== null ? ` · ${runMs}ms` : ""} · run #${runs}`
      : connectivity === "offline"
        ? `reconnecting…${queued > 0 ? ` · ${queued} queued` : ""}`
        : "connecting…";

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <View style={styles.statusRow}>
        <Text
          style={[
            styles.statusText,
            (runState === "error" || connectivity === "offline") && styles.statusTextWarn,
          ]}
        >
          {statusLine}
        </Text>
        <Pressable style={styles.replanBtn} onPress={() => dispatchAction({ type: "toast", message: "Re-plan requested" })}>
          <Text style={styles.replanText}>Re-plan</Text>
        </Pressable>
      </View>
      {parseError !== null && <Text style={styles.errorText}>rejected: {parseError}</Text>}
      {plan ? (
        <PlanBody plan={plan} committedAt={committedAt} dispatch={onChip} />
      ) : (
        <Text style={styles.muted}>
          {connectivity === "offline" ? "Backend unreachable — will sync automatically." : "Waiting for the first compose_home…"}
        </Text>
      )}
    </ScrollView>
  );
}

function PlanBody({
  plan,
  committedAt,
  dispatch,
}: {
  plan: HomePlan;
  committedAt: number | null;
  dispatch: (action: Action) => void;
}) {
  const { width } = useWindowDimensions();
  const colWidth = (width - 2 * grid.paddingH - grid.gutter) / 2;

  return (
    <>
      <View style={styles.header}>
        <View style={styles.ring}>
          <Text style={styles.ringText}>L{plan.header.level}</Text>
        </View>
        <View style={styles.headerText}>
          <Text style={styles.greeting}>{plan.header.greeting}</Text>
          <Text style={styles.dateLabel}>{plan.header.dateLabel}</Text>
        </View>
      </View>
      <Text style={styles.muted}>
        planId {plan.planId} · {plan.tiles.length} tiles · committed{" "}
        {committedAt ? new Date(committedAt).toLocaleTimeString() : "—"}
      </Text>
      <View style={styles.grid}>
        {plan.tiles.map((tile) => (
          <ProbeTile key={tile.id} tile={tile} colWidth={colWidth} dispatch={dispatch} />
        ))}
      </View>
    </>
  );
}

function ProbeTile({
  tile,
  colWidth,
  dispatch,
}: {
  tile: Tile;
  colWidth: number;
  dispatch: (action: Action) => void;
}) {
  const width = tile.layout.cols === 1 ? colWidth * 2 + grid.gutter : colWidth;
  const height = tile.layout.rows * grid.rowUnit + (tile.layout.rows - 1) * grid.gutter;
  return (
    <View
      style={[
        styles.tile,
        {
          width,
          minHeight: height,
          backgroundColor: toneBackground[tile.tone],
          borderColor: toneBorder[tile.tone],
        },
      ]}
    >
      <View style={styles.tileTop}>
        <Text style={styles.tileName}>{tile.component}</Text>
        <Text style={styles.tileTone}>{tile.tone}</Text>
      </View>
      <Text style={styles.tileBody}>{summarizeProps(tile)}</Text>
      {"chips" in tile && tile.chips.length > 0 && (
        <View style={styles.chipRow}>
          {tile.chips.map((chip) => (
            <Pressable key={chip.label} style={styles.chip} onPress={() => dispatch(chip.action)}>
              <Text style={styles.chipText}>{chip.label}</Text>
            </Pressable>
          ))}
        </View>
      )}
    </View>
  );
}

function summarizeProps(tile: Tile): string {
  const entries = Object.entries(tile.props).map(([k, v]) => {
    if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") {
      return `${k}: ${v}`;
    }
    if (Array.isArray(v)) return `${k}: [${v.length}]`;
    return `${k}: ${JSON.stringify(v)}`;
  });
  return entries.join(" · ").slice(0, 200);
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.ground },
  content: { paddingTop: 48, paddingBottom: 32, paddingHorizontal: grid.paddingH, gap: 10 },
  statusRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  statusText: { color: colors.chromeInk, fontSize: 12, fontWeight: "600", flexShrink: 1 },
  statusTextWarn: { color: "#B3402E" },
  replanBtn: {
    backgroundColor: colors.btn,
    borderRadius: radius.chip,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  replanText: { color: colors.btnInk, fontSize: 12, fontWeight: "700" },
  errorText: { color: "#B3402E", fontSize: 11 },
  muted: { color: colors.chromeMuted, fontSize: 11 },
  header: { flexDirection: "row", alignItems: "center", gap: 12, marginTop: 4 },
  ring: {
    width: 52,
    height: 52,
    borderRadius: 26,
    borderWidth: 4,
    borderColor: colors.violet,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surface,
  },
  ringText: { color: colors.ink, fontSize: 13, fontWeight: "800" },
  headerText: { gap: 2 },
  greeting: { color: colors.ink, fontSize: 22, fontWeight: "800" },
  dateLabel: { color: colors.chromeMuted, fontSize: 12 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: grid.gutter, marginTop: 4 },
  tile: {
    borderRadius: radius.card,
    borderWidth: 1,
    padding: 14,
    gap: 8,
  },
  tileTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  tileName: { color: colors.ink, fontSize: 13, fontWeight: "800" },
  tileTone: { color: colors.chromeMuted, fontSize: 10, textTransform: "uppercase" },
  tileBody: { color: colors.chromeInk, fontSize: 12, lineHeight: 17 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: "auto" },
  chip: {
    backgroundColor: colors.btn,
    borderRadius: radius.chip,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  chipText: { color: colors.btnInk, fontSize: 11, fontWeight: "700" },
});