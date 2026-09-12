import type { ComponentType } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { COPY, type Action, type Tile } from "@kinetic/ui-schema";
import { colors, radius, toneBackground, toneBorder } from "@kinetic/design-tokens";

/**
 * Component registry (§4.5) — the closed renderer set. A plan tile reaches
 * pixels only through this map; unknown components already fail ui-schema
 * validation before render. P2 scope: the 9 demo-critical components are
 * real renderings (prototype `AK.reg` silhouettes); the remaining 8 render
 * as probe cards until their workflows land (P3/P4). The map is typed
 * exhaustively over the discriminated union — adding a component to the
 * schema forces a registry entry here.
 */

export type Dispatch = (action: Action) => void;

type TileProps<K extends Tile["component"]> = {
  tile: Extract<Tile, { component: K }>;
  dispatch: Dispatch;
};
type Renderer<K extends Tile["component"]> = ComponentType<TileProps<K>>;
type Registry = { [K in Tile["component"]]: Renderer<K> };

// -- shared primitives --------------------------------------------------------

function Card({
  tile,
  children,
  center,
}: {
  tile: Tile;
  children: React.ReactNode;
  center?: boolean;
}) {
  return (
    <View
      style={[
        styles.card,
        center && styles.cardCenter,
        { backgroundColor: toneBackground[tile.tone], borderColor: toneBorder[tile.tone] },
      ]}
    >
      {children}
    </View>
  );
}

function Eyebrow({ label }: { label: string }) {
  return (
    <View style={styles.eyebrow}>
      <View style={styles.pip} />
      <Text style={styles.eyebrowText}>{label}</Text>
    </View>
  );
}

function H2({ children, size }: { children: string; size?: number }) {
  return <Text style={[styles.h2, size !== undefined && { fontSize: size }]}>{children}</Text>;
}

function Body({ children, center }: { children: string; center?: boolean }) {
  return <Text style={[styles.body, center && styles.textCenter]}>{children}</Text>;
}

function Chip({ label, onPress, basis }: { label: string; onPress: () => void; basis?: `${number}%` }) {
  return (
    <Pressable style={[styles.chip, basis !== undefined && { flexBasis: basis }]} onPress={onPress}>
      <Text style={styles.chipText}>{label}</Text>
    </Pressable>
  );
}

/** Badge disc — bordered ring + tick (no SVG dep; prototype AKB silhouette). */
function BadgeDisc({ n, earned, size }: { n: number; earned: boolean; size: number }) {
  return (
    <View
      style={[
        styles.badgeDisc,
        {
          width: size,
          height: size,
          borderRadius: size / 2,
          borderColor: earned ? colors.violet : colors.line,
        },
      ]}
    >
      <Text style={[styles.badgeDiscText, !earned && styles.badgeDiscLocked]}>{n}</Text>
    </View>
  );
}

// -- the 9 demo-critical renderers --------------------------------------------

function DosePromptCard({ tile, dispatch }: TileProps<"DosePromptCard">) {
  return (
    <Card tile={tile}>
      <Eyebrow label="Now · morning dose" />
      <H2>{tile.props.headline}</H2>
      <Body>{tile.props.reassurance}</Body>
      <View style={styles.chipGrid}>
        {tile.chips.map((c) => (
          <Chip key={c.label} label={c.label} onPress={() => dispatch(c.action)} />
        ))}
      </View>
    </Card>
  );
}

function TeamQuestionCard({ tile, dispatch }: TileProps<"TeamQuestionCard">) {
  return (
    <Card tile={tile}>
      <Eyebrow label="Your care team asks" />
      <H2 size={18}>{tile.props.text}</H2>
      <View style={styles.chipRow3}>
        {tile.chips.map((c) => (
          <Chip key={c.label} label={c.label} basis="30%" onPress={() => dispatch(c.action)} />
        ))}
      </View>
    </Card>
  );
}

function ThanksCard({ tile }: TileProps<"ThanksCard">) {
  return (
    <Card tile={tile} center>
      <H2 size={20}>{COPY.thanksTitle}</H2>
      <Body center>{COPY.thanksBody}</Body>
      {tile.props.plus && (
        <View style={styles.plusPill}>
          <Text style={styles.plusPillText}>+1 check-in</Text>
        </View>
      )}
      <Text style={styles.progText}>{tile.props.progressText}</Text>
    </Card>
  );
}

function AllClearCard({ tile }: TileProps<"AllClearCard">) {
  return (
    <Card tile={tile} center>
      <H2 size={20}>{COPY.allClearTitle}</H2>
      <Body center>{COPY.allClearBody}</Body>
    </Card>
  );
}

function DoneRow({ tile }: TileProps<"DoneRow">) {
  return (
    <Card tile={tile}>
      <View style={styles.stripRow}>
        <View style={styles.doneDot} />
        <Text style={styles.stripLabel}>{tile.props.label}</Text>
        <Text style={styles.stripStatus}>{tile.props.status}</Text>
      </View>
    </Card>
  );
}

function BadgesSquare({ tile }: TileProps<"BadgesSquare">) {
  return (
    <Card tile={tile}>
      <Eyebrow label="Badges" />
      <View style={styles.squareBody}>
        <BadgeDisc n={1} earned size={44} />
        <Text style={styles.progText}>{tile.props.progressText}</Text>
      </View>
    </Card>
  );
}

function CareTeamSquare({ tile }: TileProps<"CareTeamSquare">) {
  return (
    <Card tile={tile}>
      <Eyebrow label="Your care team" />
      <View style={styles.squareBody}>
        <Text style={styles.progText}>Call or message</Text>
      </View>
    </Card>
  );
}

function ReminderStrip({ tile }: TileProps<"ReminderStrip">) {
  return (
    <Card tile={tile}>
      <View style={styles.stripRow}>
        <View style={styles.infoDot} />
        <Text style={styles.stripLabel}>{tile.props.text}</Text>
      </View>
    </Card>
  );
}

function BadgeCelebrationCard({ tile, dispatch }: TileProps<"BadgeCelebrationCard">) {
  const { n, label, copy, shelf } = tile.props;
  return (
    <Card tile={tile} center>
      <View style={[styles.celebrateRing, { width: 112, height: 112, borderRadius: 56 }]}>
        <Text style={styles.celebrateTick}>✓</Text>
      </View>
      <Eyebrow label="Badge unlocked" />
      <H2 size={20}>{`${label} · ${n} check-ins`}</H2>
      <Body center>{copy}</Body>
      <View style={styles.shelf}>
        {shelf.map((s) => (
          <BadgeDisc key={s.n} n={s.n} earned={s.earned} size={44} />
        ))}
      </View>
      <Pressable style={styles.keepGoing} onPress={() => dispatch({ type: "dismiss_celebration" })}>
        <Text style={styles.chipText}>Keep going</Text>
      </Pressable>
    </Card>
  );
}

// -- probe fallback for the 8 not-yet-wired components (P3/P4) ----------------

function ProbeTile({ tile, dispatch }: { tile: Tile; dispatch: Dispatch }) {
  return (
    <Card tile={tile}>
      <View style={styles.tileTop}>
        <Text style={styles.tileName}>{tile.component}</Text>
        <Text style={styles.tileTone}>{tile.tone}</Text>
      </View>
      <Text style={styles.probeBody}>
        {Object.entries(tile.props)
          .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
          .join(" · ")
          .slice(0, 200)}
      </Text>
      {"chips" in tile && (
        <View style={styles.chipRow}>
          {tile.chips.map((c) => (
            <Chip key={c.label} label={c.label} onPress={() => dispatch(c.action)} />
          ))}
        </View>
      )}
    </Card>
  );
}

// -- the exhaustive map (§4.5: unknown component = validation failure) --------

export const registry: Registry = {
  // real renderings (P2 demo set)
  DosePromptCard,
  TeamQuestionCard,
  ThanksCard,
  AllClearCard,
  DoneRow,
  BadgesSquare,
  CareTeamSquare,
  ReminderStrip,
  BadgeCelebrationCard,
  // probe cards until their workflows land (P3/P4)
  TemperatureCard: ProbeTile,
  SamplePrepCard: ProbeTile,
  VomitCheckCard: ProbeTile,
  NewMedCard: ProbeTile,
  HandoffCard: ProbeTile,
  DiarySharedCard: ProbeTile,
  BookedRow: ProbeTile,
};

export function TileView({ tile, dispatch }: { tile: Tile; dispatch: Dispatch }) {
  const Renderer = registry[tile.component] as Renderer<Tile["component"]>;
  return <Renderer tile={tile} dispatch={dispatch} />;
}

const styles = StyleSheet.create({
  card: {
    borderRadius: radius.card,
    borderWidth: 1,
    padding: 14,
    gap: 8,
    flex: 1,
  },
  cardCenter: { alignItems: "center", justifyContent: "center" },
  textCenter: { textAlign: "center" },
  eyebrow: { flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start" },
  pip: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.violet },
  eyebrowText: { color: colors.muted, fontSize: 11, fontWeight: "700", textTransform: "uppercase" },
  h2: { color: colors.ink, fontSize: 22, fontWeight: "800", lineHeight: 27 },
  body: { color: colors.muted, fontSize: 13, lineHeight: 18 },
  chipGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: "auto" },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: "auto" },
  chip: {
    backgroundColor: colors.btn,
    borderRadius: radius.chip,
    paddingHorizontal: 12,
    paddingVertical: 10,
    minHeight: 44,
    justifyContent: "center",
    flexGrow: 1,
    flexShrink: 1,
    flexBasis: "46%",
  },
  // three-answer rows (TeamQuestionCard) sit on one line (§4.5 chip counts)
  chipRow3: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: "auto" },
  chipText: { color: colors.btnInk, fontSize: 12, fontWeight: "700", textAlign: "center" },
  plusPill: {
    backgroundColor: colors.violet,
    borderRadius: radius.chip,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  plusPillText: { color: colors.btnInk, fontSize: 12, fontWeight: "800" },
  progText: { color: colors.muted, fontSize: 12, fontWeight: "600", textAlign: "center" },
  stripRow: { flexDirection: "row", alignItems: "center", gap: 8, flex: 1 },
  stripLabel: { color: colors.ink, fontSize: 13, fontWeight: "700", flexShrink: 1 },
  stripStatus: { color: colors.muted, fontSize: 12, marginLeft: "auto" },
  doneDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.done },
  infoDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.cyan },
  squareBody: { alignItems: "center", justifyContent: "center", gap: 8, flex: 1 },
  badgeDisc: {
    borderWidth: 3,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.raised,
  },
  badgeDiscText: { color: colors.ink, fontSize: 14, fontWeight: "800" },
  badgeDiscLocked: { color: colors.muted, opacity: 0.5 },
  celebrateRing: {
    borderWidth: 4,
    borderColor: colors.violet,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.raised,
    marginTop: 4,
  },
  celebrateTick: { color: colors.done, fontSize: 40, fontWeight: "800" },
  shelf: { flexDirection: "row", gap: 8, marginTop: 4 },
  keepGoing: {
    backgroundColor: colors.btn,
    borderRadius: radius.chip,
    paddingHorizontal: 24,
    paddingVertical: 10,
    minHeight: 44,
    justifyContent: "center",
    marginTop: 8,
  },
  tileTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  tileName: { color: colors.ink, fontSize: 13, fontWeight: "800" },
  tileTone: { color: colors.muted, fontSize: 10, textTransform: "uppercase" },
  probeBody: { color: colors.ink, fontSize: 12, lineHeight: 17 },
});
