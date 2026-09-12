import { useAgent, useCopilotKit } from "@copilotkit/react-native/headless";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, ToastAndroid, View, useWindowDimensions } from "react-native";
import { colors, grid, radius, toneBackground, toneBorder } from "@kinetic/design-tokens";
import type { Action, HomePlan, Tile } from "@kinetic/ui-schema";
import { usePlanStore } from "../plan/store";

type RunState = "idle" | "running" | "ok" | "error";

/**
 * P0 probe screen: grounds the on-emulator exit proof. Renders the last
 * committed plan from the real ui_agent round-trip over 10.0.2.2:8200.
 * The full 17-component registry is P2 (§5.3) — tiles render as
 * tone-tinted probe cards with the closed Action bus wired to toasts.
 */
export default function ProbeHome() {
  const { copilotkit } = useCopilotKit();
  const { agent, isReady } = useAgent({ agentId: "ui_agent" });
  const plan = usePlanStore((s) => s.plan);
  const committedAt = usePlanStore((s) => s.committedAt);
  const parseError = usePlanStore((s) => s.parseError);
  const [runState, setRunState] = useState<RunState>("idle");
  const [runMs, setRunMs] = useState<number | null>(null);
  const [runs, setRuns] = useState(0);

  const run = useCallback(async () => {
    setRunState("running");
    const t0 = Date.now();
    try {
      await copilotkit.runAgent({ agent });
      setRunMs(Date.now() - t0);
      setRuns((n) => n + 1);
      setRunState("ok");
    } catch (err) {
      setRunState("error");
      console.warn("[probe] runAgent failed:", err);
    }
  }, [copilotkit, agent]);

  useEffect(() => {
    if (isReady) void run();
  }, [isReady, run]);

  const dispatch = useCallback((action: Action) => {
    // Closed action vocabulary (§4.5) — P0 probe logs the bus event; the
    // registry + data-api writes consume it in P1+.
    console.log("[action]", JSON.stringify(action));
    ToastAndroid.show(JSON.stringify(action), ToastAndroid.SHORT);
  }, []);

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <View style={styles.statusRow}>
        <Text style={[styles.statusText, runState === "error" && styles.statusTextError]}>
          ui_agent · {runState}
          {runMs !== null ? ` · ${runMs}ms` : ""} · run #{runs}
        </Text>
        <Pressable style={styles.replanBtn} onPress={() => void run()}>
          <Text style={styles.replanText}>Re-plan</Text>
        </Pressable>
      </View>
      {parseError !== null && <Text style={styles.errorText}>rejected: {parseError}</Text>}
      {plan ? <PlanBody plan={plan} committedAt={committedAt} dispatch={dispatch} /> : (
        <Text style={styles.muted}>
          {runState === "error" ? "Runtime unreachable — check compose stack." : "Waiting for the first compose_home…"}
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
  const colWidth = useMemo(
    () => (width - 2 * grid.paddingH - grid.gutter) / 2,
    [width],
  );

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
            <Pressable
              key={chip.label}
              style={styles.chip}
              onPress={() => dispatch(chip.action)}
            >
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
  statusText: { color: colors.chromeInk, fontSize: 12, fontWeight: "600" },
  statusTextError: { color: "#B3402E" },
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