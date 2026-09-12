/**
 * Prototype CSS custom properties (phone-app-prototype-v2.html :root) → RN theme.
 * Fonts are bundled via expo-font in the app (see §5.7 build ledger); until that
 * lands, `display`/`sans` fall back to the RN system font.
 */

export const colors = {
  chrome: "#EAE3D2",
  chromeInk: "#1F3229",
  chromeMuted: "#5F6D60",
  chromeLine: "#D8CFB8",
  chromeCard: "#F6F2E7",
  ground: "#F6F2E7",
  surface: "#FFFDF8",
  raised: "#EFE9DA",
  line: "#E3DAC6",
  ink: "#1F3229",
  muted: "#5F6D60",
  btn: "#1E7A54",
  btnInk: "#FFFFFF",
  cyan: "#5FB4D6",
  violet: "#52B584",
  magenta: "#E2C488",
  accentText: "#1D6E96",
  done: "#1E7A54",
  doneTint: "#E3F5EE",
  tile: "#1F3229",
  frame: "#D8CFB8",
} as const;

export const toneBackground: Record<string, string> = {
  hot: "rgba(82,181,132,0.10)",
  high: "rgba(82,181,132,0.15)",
  info: "rgba(95,180,214,0.20)",
  game: "rgba(226,196,136,0.22)",
  good: "rgba(30,122,84,0.12)",
  calm: "rgba(255,253,248,1)",
  done: "rgba(255,253,248,1)",
};

export const toneBorder: Record<string, string> = {
  hot: "rgba(82,181,132,0.6)",
  high: "rgba(82,181,132,0.45)",
  info: "rgba(95,180,214,0.65)",
  game: "rgba(226,196,136,0.7)",
  good: "rgba(30,122,84,0.45)",
  calm: "#E3DAC6",
  done: "#E3DAC6",
};

/** Bento grid unit — grid-auto-rows: 82px + 12px gap (§5.7 ledger). */
export const grid = {
  rowUnit: 82,
  gutter: 12,
  paddingH: 16,
};

export const radius = { card: 20, chip: 14, sheet: 28 } as const;

export const typography = {
  display: "Poppins", // bundled via expo-font when added (§5.7)
  sans: "Manrope",
  fallback: undefined as string | undefined,
} as const;
