import { useState } from "react";
import { ActivityIndicator, Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { colors, radius } from "@kinetic/design-tokens";
import { api, ApiError } from "../data/api";
import { useVoiceFixture } from "../voice/fixture";

/**
 * ScenarioDrawer (§5.5 dev harness) — reseeds the local data-api into a demo
 * scenario state, then the caller re-probes + re-plans. The stage lever:
 * live scenario switching, no psql.
 */

export type ScenarioName = "morning" | "question" | "badge" | "clear" | "health" | "sick" | "diary";

const SCENARIOS: { name: ScenarioName; label: string }[] = [
  { name: "morning", label: "Morning dose (31 · dose due)" },
  { name: "question", label: "Care-team question" },
  { name: "badge", label: "Badge day (99 → tap dose)" },
  { name: "clear", label: "All clear" },
  { name: "health", label: "Voice · health question (hold FAB)" },
  { name: "sick", label: "Sick day · symptom chains" },
  { name: "diary", label: "Diary entry shared" },
];

export function ScenarioDrawer({
  open,
  onClose,
  onSeeded,
}: {
  open: boolean;
  onClose: () => void;
  onSeeded: (name: ScenarioName) => void;
}) {
  const [busy, setBusy] = useState<ScenarioName | null>(null);
  const [fixtureBusy, setFixtureBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const runFluFixture = useVoiceFixture((s) => s.runFluFixture);

  const seed = async (name: ScenarioName) => {
    setBusy(name);
    setError(null);
    try {
      await api.scenario(name);
      onClose();
      onSeeded(name);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal visible={open} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.scrim} onPress={onClose}>
        <Pressable style={styles.sheet} onPress={() => {}}>
          <Text style={styles.title}>Scenarios</Text>
          {SCENARIOS.map((s) => (
            <Pressable key={s.name} style={styles.row} disabled={busy !== null} onPress={() => void seed(s.name)}>
              {busy === s.name ? (
                <ActivityIndicator size="small" color={colors.btn} />
              ) : (
                <Text style={styles.rowText}>{s.label}</Text>
              )}
            </Pressable>
          ))}
          <Pressable
            style={[styles.row, styles.fixtureRow]}
            disabled={fixtureBusy || runFluFixture === null}
            onPress={() => {
              setFixtureBusy(true);
              void runFluFixture?.().finally(() => {
                setFixtureBusy(false);
                onClose();
              });
            }}
          >
            {fixtureBusy ? (
              <ActivityIndicator size="small" color={colors.violet} />
            ) : (
              <Text style={[styles.rowText, styles.fixtureText]}>🎙 Demo audio · "I have a flu" (on-device whisper)</Text>
            )}
          </Pressable>
          {error !== null && <Text style={styles.error} numberOfLines={2}>{error}</Text>}
          <Pressable style={[styles.row, styles.cancel]} onPress={onClose}>
            <Text style={styles.rowText}>Close</Text>
          </Pressable>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  scrim: { flex: 1, backgroundColor: "rgba(31,50,41,0.4)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.sheet,
    borderTopRightRadius: radius.sheet,
    padding: 16,
    paddingTop: 20,
    gap: 8,
  },
  title: { color: colors.ink, fontSize: 14, fontWeight: "800", marginBottom: 4 },
  row: {
    backgroundColor: colors.raised,
    borderRadius: radius.chip,
    paddingHorizontal: 14,
    paddingVertical: 12,
    minHeight: 48,
    justifyContent: "center",
  },
  cancel: { backgroundColor: "transparent", borderWidth: 1, borderColor: colors.line, marginTop: 4 },
  fixtureRow: { backgroundColor: colors.violet, marginTop: 4 },
  fixtureText: { color: colors.btnInk },
  rowText: { color: colors.ink, fontSize: 13, fontWeight: "600" },
  error: { color: "#B3402E", fontSize: 11 },
});
