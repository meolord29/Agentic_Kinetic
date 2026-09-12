import { useAgent, useCopilotKit } from "@copilotkit/react-native/headless";
import { useCallback, useEffect, useRef, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, ToastAndroid, View, useWindowDimensions } from "react-native";
import { colors, grid, radius } from "@kinetic/design-tokens";
import { type Action, type HomePlan, type Tile } from "@kinetic/ui-schema";
import { usePlanStore } from "../plan/store";
import { TileView } from "../plan/registry";
import { ScenarioDrawer, type ScenarioName } from "../dev/ScenarioDrawer";
import { dispatchAction, probeAndRefresh, useSnapshotLifecycle, useSnapshotStore } from "../data/snapshot";

type RunState = "idle" | "running" | "ok" | "error";

/**
 * Home (§4.7 plan loop, P2 registry edition):
 *   chip tap → dispatchAction (optimistic + §5.6 queue) → runAgent
 *   → compose_home → ui-schema gate → commit → registry render.
 * Tiles render through the §4.5 registry (real components for the P2 demo
 * set, probe cards for the rest). Dev chip opens the ScenarioDrawer (§5.5).
 */
export default function Home() {
  useSnapshotLifecycle();

  const { copilotkit } = useCopilotKit();
  const { agent, isReady } = useAgent({ agentId: "ui_agent" });
  const plan = usePlanStore((s) => s.plan);
  const dismissedBadgeN = usePlanStore((s) => s.dismissedBadgeN);
  const parseError = usePlanStore((s) => s.parseError);
  const connectivity = useSnapshotStore((s) => s.connectivity);
  const queued = useSnapshotStore((s) => s.queued);
  const planNonce = useSnapshotStore((s) => s.planNonce);
  const [runState, setRunState] = useState<RunState>("idle");
  const [drawerOpen, setDrawerOpen] = useState(false);

  const run = useCallback(async () => {
    setRunState("running");
    const t0 = Date.now();
    try {
      // v2 note: yield a macrotask so a just-registered agent context commits
      // before the run reads it (CopilotKitRN ledger §5.1).
      await new Promise((r) => setTimeout(r, 30));
      console.log("[run] start");
      await copilotkit.runAgent({ agent });
      setRunState("ok");
      console.log("[run] ok", Date.now() - t0, "ms");
    } catch (err) {
      setRunState("error");
      console.warn("[home] runAgent failed:", err);
    }
  }, [copilotkit, agent]);

  const runRef = useRef(run);
  runRef.current = run;

  useEffect(() => {
    if (isReady) void runRef.current();
  }, [isReady, planNonce]);

  const onChip = useCallback((action: Action) => {
    console.log("[action]", JSON.stringify(action));
    if (action.type === "dismiss_celebration") {
      // P2 demo accommodation — server ack lands in P4; suppress locally until
      // the next scenario seed (the §5.6 celebration window stays live).
      usePlanStore.getState().dismissCelebration();
      ToastAndroid.show("Nice — keep going!", ToastAndroid.SHORT);
      return;
    }
    dispatchAction(action);
  }, []);

  const onScenarioSeeded = useCallback((name: ScenarioName) => {
    usePlanStore.getState().resetDismissal();
    ToastAndroid.show(`scenario: ${name}`, ToastAndroid.SHORT);
    void (async () => {
      await probeAndRefresh();
      dispatchAction({ type: "toast", message: "re-plan" }); // bump → agent run
    })();
  }, []);

  const statusLine =
    connectivity === "online"
      ? `ui_agent · ${runState}`
      : connectivity === "offline"
        ? `reconnecting…${queued > 0 ? ` · ${queued} queued` : ""}`
        : "connecting…";

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <View style={styles.statusRow}>
        <Text style={[styles.statusText, (runState === "error" || connectivity === "offline") && styles.statusTextWarn]}>
          {statusLine}
        </Text>
        <View style={styles.statusBtns}>
          <Pressable style={styles.replanBtn} onPress={() => dispatchAction({ type: "toast", message: "Re-plan requested" })}>
            <Text style={styles.replanText}>Re-plan</Text>
          </Pressable>
          <Pressable style={[styles.replanBtn, styles.scenarioBtn]} onPress={() => setDrawerOpen(true)}>
            <Text style={styles.replanText}>Scenarios</Text>
          </Pressable>
        </View>
      </View>
      {parseError !== null && <Text style={styles.errorText}>rejected: {parseError}</Text>}
      {plan ? (
        <PlanBody plan={plan} dismissedBadgeN={dismissedBadgeN} dispatch={onChip} />
      ) : (
        <Text style={styles.muted}>
          {connectivity === "offline" ? "Backend unreachable — will sync automatically." : "Waiting for the first compose_home…"}
        </Text>
      )}
      <ScenarioDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} onSeeded={onScenarioSeeded} />
    </ScrollView>
  );
}

function PlanBody({
  plan,
  dismissedBadgeN,
  dispatch,
}: {
  plan: HomePlan;
  dismissedBadgeN: number | null;
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
      <View style={styles.grid}>
        {plan.tiles
          .filter((t) => !(t.component === "BadgeCelebrationCard" && t.props.n === dismissedBadgeN))
          .map((tile) => (
            <TileFrame key={tile.id} tile={tile} colWidth={colWidth} dispatch={dispatch} />
          ))}
      </View>
    </>
  );
}

function TileFrame({
  tile,
  colWidth,
  dispatch,
}: {
  tile: Tile;
  colWidth: number;
  dispatch: (action: Action) => void;
}) {
  // cols is the span count out of 2 (§4.2): 2 = full width, 1 = half width.
  const width = tile.layout.cols === 2 ? colWidth * 2 + grid.gutter : colWidth;
  const height = tile.layout.rows * grid.rowUnit + (tile.layout.rows - 1) * grid.gutter;
  return (
    <View style={{ width, minHeight: height, flexDirection: "row" }}>
      <TileView tile={tile} dispatch={dispatch} />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.ground },
  content: { paddingTop: 48, paddingBottom: 32, paddingHorizontal: grid.paddingH, gap: 10 },
  statusRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  statusText: { color: colors.chromeInk, fontSize: 12, fontWeight: "600", flexShrink: 1 },
  statusTextWarn: { color: "#B3402E" },
  statusBtns: { flexDirection: "row", gap: 8 },
  replanBtn: {
    backgroundColor: colors.btn,
    borderRadius: radius.chip,
    paddingHorizontal: 14,
    paddingVertical: 8,
    minHeight: 36,
    justifyContent: "center",
  },
  scenarioBtn: { backgroundColor: colors.cyan },
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
});
