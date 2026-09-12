import { useState } from "react";
import { ActivityIndicator, Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { colors, radius } from "@kinetic/design-tokens";
import { api, ApiError } from "../data/api";

/**
 * ScenarioDrawer (§5.5 dev harness) — reseeds the local data-api into a demo
 * scenario state, then the caller re-probes + re-plans. The stage lever:
 * live scenario switching, no psql.
 */

export type ScenarioName = "morning" | "question" | "badge" | "clear";

const SCENARIOS: { name: ScenarioName; label: string }[] = [
  { name: "morning", label: "Morning dose (31 · dose due)" },
  { name: "question", label: "Care-team question" },
  { name: "badge", label: "Badge day (99 → tap dose)" },
  { name: "clear", label: "All clear" },
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
  const [error, setError] = useState<string | null>(null);

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
  rowText: { color: colors.ink, fontSize: 13, fontWeight: "600" },
  error: { color: "#B3402E", fontSize: 11 },
});
