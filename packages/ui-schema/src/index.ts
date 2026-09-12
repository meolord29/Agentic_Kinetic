/**
 * Agentic Kinetic — UI Description Contract (architecture-design.md §4.2).
 *
 * Down-channel:  HomePlan              (ui_agent → client, via the `compose_home` frontend tool)
 * Up-channel:    PatientContextSummary (client → ui_agent, via agent context)
 *
 * The agent owns WHAT is on screen; this schema owns WHAT IS POSSIBLE. Anything the
 * planner emits that does not validate here can never reach pixels (§4.6 fallback).
 */
import { z } from "zod";

export const Tone = z.enum(["hot", "high", "info", "game", "good", "calm", "done"]);
export type Tone = z.infer<typeof Tone>;

export const Layout = z.object({
  cols: z.union([z.literal(1), z.literal(2)]),
  rows: z.number().int().min(1).max(5),
});
export type Layout = z.infer<typeof Layout>;

// Exact layout schemas (prototype silhouettes, §4.2 layout constants)
const Layout2x5 = z.object({ cols: z.literal(2), rows: z.literal(5) }); // celebrations only
const Layout2x3 = z.object({ cols: z.literal(2), rows: z.literal(3) }); // main hot cards
const Layout2x2 = z.object({ cols: z.literal(2), rows: z.literal(2) }); // questions / thanks / all-clear
const Layout1x4 = z.object({ cols: z.literal(1), rows: z.literal(4) }); // temperature — half-width, tall
const Layout1x2 = z.object({ cols: z.literal(1), rows: z.literal(2) }); // squares
const LayoutStrip = z.object({ cols: z.literal(2), rows: z.literal(1) }); // 1-row strips

// Plain constants for planner/render use (typed as the exact shapes above)
export const LAYOUT_2x5 = { cols: 2, rows: 5 } as const;
export const LAYOUT_2x3 = { cols: 2, rows: 3 } as const;
export const LAYOUT_2x2 = { cols: 2, rows: 2 } as const;
export const LAYOUT_1x4 = { cols: 1, rows: 4 } as const;
export const LAYOUT_1x2 = { cols: 1, rows: 2 } as const;
export const LAYOUT_STRIP = { cols: 2, rows: 1 } as const;

/** The closed action vocabulary — the `data-*` bus from the prototype (§4.5). */
export const Action = z.discriminatedUnion("type", [
  z.object({ type: z.literal("go"), target: z.enum(["now", "milestone", "settings"]) }),
  z.object({ type: z.literal("answer_dose"), value: z.enum(["taken", "late", "missed", "not_sure"]) }),
  z.object({
    type: z.literal("answer_temperature"),
    value: z.enum(["v36_5", "v37_0", "v37_5", "v38_plus", "not_measured"]),
  }),
  z.object({ type: z.literal("answer_question"), value: z.enum(["yes", "no", "not_sure"]) }),
  z.object({ type: z.literal("answer_med_start"), value: z.enum(["yes", "no", "not_sure"]) }),
  z.object({
    type: z.literal("answer_med_timing"),
    value: z.enum(["same_time", "different_time", "not_sure"]),
  }),
  z.object({ type: z.literal("answer_vomit"), value: z.enum(["within_hour", "later", "didnt_take"]) }),
  z.object({ type: z.literal("ack_reminder"), id: z.string() }),
  z.object({ type: z.literal("confirm_voice_note") }),
  z.object({ type: z.literal("dismiss_celebration") }),
  z.object({ type: z.literal("tour"), dir: z.enum(["next", "back", "skip", "start_checkin"]) }),
  z.object({ type: z.literal("call_care_team") }),
  z.object({ type: z.literal("toast"), message: z.string().max(120) }),
]);
export type Action = z.infer<typeof Action>;

export const Chip = z.object({
  label: z.string().max(24),
  action: Action,
});
export type Chip = z.infer<typeof Chip>;

const chips = (n: number) => z.array(Chip).length(n);

/** Exactly 17 tile components — the whole rendering vocabulary (§4.5). */
export const Tile = z.discriminatedUnion("component", [
  z.object({
    component: z.literal("DosePromptCard"),
    id: z.string(),
    layout: Layout2x3,
    tone: z.literal("hot"),
    props: z.object({ headline: z.string(), reassurance: z.literal("Every answer counts the same.") }),
    chips: chips(4),
  }),
  z.object({
    component: z.literal("TemperatureCard"),
    id: z.string(),
    layout: Layout1x4,
    tone: z.literal("hot"),
    props: z.object({ reason: z.enum(["scheduled", "sick_day"]) }),
    chips: chips(5),
  }),
  z.object({
    component: z.literal("TeamQuestionCard"),
    id: z.string(),
    layout: Layout2x2,
    tone: z.literal("hot"),
    props: z.object({ text: z.string() }), // VERBATIM care-team text — validator compares to DB row
    chips: chips(3),
  }),
  z.object({
    component: z.literal("SamplePrepCard"),
    id: z.string(),
    layout: Layout2x3,
    tone: z.literal("hot"),
    props: z.object({
      when: z.string(),
      stops: z.array(z.string()).length(4),
      notes: z.string(),
    }),
  }),
  z.object({
    component: z.literal("VomitCheckCard"),
    id: z.string(),
    layout: Layout2x3,
    tone: z.literal("hot"),
    props: z.object({}),
    chips: chips(3),
  }),
  z.object({
    component: z.literal("NewMedCard"),
    id: z.string(),
    layout: Layout,
    tone: z.literal("hot"),
    props: z.object({ step: z.union([z.literal(1), z.literal(2)]) }),
    chips: chips(3), // step 1 → answer_med_start · step 2 → answer_med_timing
  }),
  z.object({
    component: z.literal("HandoffCard"),
    id: z.string(),
    layout: Layout2x3,
    tone: z.literal("high"),
    props: z.object({ q: z.string(), receipt: z.string() }), // q VERBATIM
  }),
  z.object({
    component: z.literal("DiarySharedCard"),
    id: z.string(),
    layout: Layout2x3,
    tone: z.literal("high"),
    props: z.object({ text: z.string(), receipt: z.string() }), // text VERBATIM
  }),
  z.object({
    component: z.literal("BadgeCelebrationCard"),
    id: z.string(),
    layout: Layout2x5,
    tone: z.literal("hot"),
    props: z.object({
      n: z.number(),
      label: z.string(),
      copy: z.string(),
      shelf: z.array(z.object({ n: z.number(), earned: z.boolean() })),
    }),
  }),
  z.object({
    component: z.literal("ThanksCard"),
    id: z.string(),
    layout: Layout2x2,
    tone: z.literal("good"),
    props: z.object({ plus: z.boolean(), progressText: z.string() }),
  }),
  z.object({
    component: z.literal("AllClearCard"),
    id: z.string(),
    layout: Layout2x2,
    tone: z.literal("calm"),
    props: z.object({}),
  }),
  z.object({
    component: z.literal("DoneRow"),
    id: z.string(),
    layout: LayoutStrip,
    tone: z.literal("done"),
    props: z.object({ label: z.string(), status: z.string() }),
  }),
  z.object({
    component: z.literal("BookedRow"),
    id: z.string(),
    layout: LayoutStrip,
    tone: z.literal("high"),
    props: z.object({
      label: z.literal("Booked by your care team"),
      when: z.string(),
      test: z.string(),
    }),
  }),
  z.object({
    component: z.literal("ReminderStrip"),
    id: z.string(),
    layout: LayoutStrip,
    tone: z.literal("info"),
    props: z.object({ text: z.string() }),
  }),
  z.object({
    component: z.literal("BadgesSquare"),
    id: z.string(),
    layout: Layout1x2,
    tone: z.literal("game"),
    props: z.object({ progressText: z.string() }),
  }),
  z.object({
    component: z.literal("CareTeamSquare"),
    id: z.string(),
    layout: Layout1x2,
    tone: z.literal("calm"),
    props: z.object({}),
  }),
]);
export type Tile = z.infer<typeof Tile>;

export const Overlay = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("tour"),
    step: z.number().int().min(0).max(4),
    target: z.enum(["agent-stack", "hot-tile", "fab", "level-ring", "menu"]),
    headline: z.string(),
    purpose: z.string(),
    last: z.boolean(),
  }),
  z.object({
    kind: z.literal("voiceResult"),
    variant: z.enum(["dose", "health", "sick", "diary", "command_matched", "command_unmatched"]),
    said: z.string(), // VERBATIM transcript
    noted: z
      .array(z.object({ label: z.string(), value: z.string(), changeable: z.boolean() }))
      .default([]),
    workflow: z.string().nullable().default(null),
  }),
]);
export type Overlay = z.infer<typeof Overlay>;

export const HomePlanHeader = z.object({
  greeting: z.string(),
  dateLabel: z.string(),
  level: z.number().int().min(1),
  levelPct: z.number().min(0).max(100),
});
export type HomePlanHeader = z.infer<typeof HomePlanHeader>;

export const HomePlan = z.object({
  planId: z.string(),
  header: HomePlanHeader,
  tiles: z.array(Tile).max(14),
  overlays: z.array(Overlay).max(1).default([]),
});
export type HomePlan = z.infer<typeof HomePlan>;

/** The UP-channel contract (§4.2/§4.3): what the client registers via agent context. */
export const PatientContextSummary = z.object({
  generatedAt: z.string(),
  user: z.object({
    displayName: z.string(),
    daypart: z.enum(["morning", "evening"]),
    dateLabel: z.string(),
    language: z.enum(["en", "zh-Hant"]),
    registered: z.boolean(),
  }),
  consent: z.object({
    deidentifiedResearch: z.boolean(),
  }),
  progress: z.object({
    checkins: z.number().int().min(0),
    level: z.number().int().min(1),
    levelPct: z.number().min(0).max(100),
    nextBadge: z
      .object({ n: z.number(), label: z.string(), remaining: z.number().int() })
      .nullable(),
    unlockPending: z.object({ n: z.number(), label: z.string() }).nullable(),
  }),
  due: z.object({
    dose: z.discriminatedUnion("status", [
      z.object({ status: z.literal("due") }),
      z.object({ status: z.literal("done"), answer: z.enum(["taken", "late", "missed", "not_sure"]) }),
    ]),
    nextSample: z.object({
      booked: z.boolean(),
      when: z.string().nullable(),
      tomorrow: z.boolean(),
      test: z.string().nullable(),
      fasting: z.boolean().nullable(),
    }),
    temperature: z.object({
      due: z.boolean(),
      reason: z.enum(["scheduled", "sick_day"]).nullable(),
    }),
    teamQuestion: z.object({
      waiting: z.boolean(),
      text: z.string().nullable(), // VERBATIM — only present while waiting
    }),
    medWatch: z.object({
      active: z.boolean(),
      step: z.union([z.literal(1), z.literal(2)]).nullable(),
    }),
    vomitCheck: z.object({ waiting: z.boolean() }),
    reminders: z.array(
      z.object({
        id: z.string(),
        text: z.string(),
        kind: z.enum(["night_before_prep", "checkin_nudge", "booking_reminder"]),
      }),
    ),
  }),
  pins: z.object({
    handoff: z.boolean(),
    diaryShared: z.boolean(),
  }),
  tour: z.object({ completed: z.boolean(), active: z.boolean() }),
});
export type PatientContextSummary = z.infer<typeof PatientContextSummary>;

// ---------------------------------------------------------------------------
// §4.6 deterministic plan invariants (guardrail validators)
// ---------------------------------------------------------------------------

export interface PlanSnapshot {
  /** The patient context the plan claims to be grounded in. */
  context: PatientContextSummary;
  /** True within one plan of a dose answer (drives ThanksCard.plus). */
  recentDoseAnswer: boolean;
}

export type PlanViolation =
  | "unknown_component"
  | "inadmissible_tile"
  | "verbatim_diff"
  | "plus_outside_dose_window"
  | "badge_not_at_threshold"
  | "multiple_hot_question_tiles"
  | "celebration_suppresses_thanks";

export const BADGE_THRESHOLDS = [1, 7, 30, 100, 365] as const;

function tileAdmissible(tile: Tile, ctx: PatientContextSummary): boolean {
  switch (tile.component) {
    case "DosePromptCard":
      return ctx.due.dose.status === "due";
    case "TemperatureCard":
      return ctx.due.temperature.due;
    case "TeamQuestionCard":
      return ctx.due.teamQuestion.waiting;
    case "SamplePrepCard":
    case "BookedRow":
      return ctx.due.nextSample.booked;
    case "VomitCheckCard":
      return ctx.due.vomitCheck.waiting;
    case "NewMedCard":
      return ctx.due.medWatch.active;
    case "BadgeCelebrationCard":
      return ctx.progress.unlockPending !== null;
    case "HandoffCard":
      return ctx.pins.handoff;
    case "DiarySharedCard":
      return ctx.pins.diaryShared;
    case "ThanksCard":
    case "DoneRow":
    case "BadgesSquare":
    case "CareTeamSquare":
    case "ReminderStrip":
    case "AllClearCard":
      return true;
  }
}

function verbatimOk(tile: Tile, ctx: PatientContextSummary): boolean {
  if (tile.component === "TeamQuestionCard") {
    return tile.props.text === (ctx.due.teamQuestion.text ?? "\u0000never-matches");
  }
  return true;
}

/**
 * Validate a plan against the snapshot. Runs at emit time (runtime) and commit
 * time (client). Any failure → caller substitutes the all-clear fallback plan.
 */
export function validatePlan(plan: HomePlan, snap: PlanSnapshot): PlanViolation[] {
  const violations: PlanViolation[] = [];
  const ctx = snap.context;

  for (const tile of plan.tiles) {
    if (!Tile.safeParse(tile).success) {
      violations.push("unknown_component");
      continue;
    }
    if (!tileAdmissible(tile, ctx)) violations.push("inadmissible_tile");
    if (!verbatimOk(tile, ctx)) violations.push("verbatim_diff");
    if (tile.component === "ThanksCard" && tile.props.plus && !snap.recentDoseAnswer) {
      violations.push("plus_outside_dose_window");
    }
    if (
      tile.component === "BadgeCelebrationCard" &&
      !BADGE_THRESHOLDS.includes(tile.props.n as (typeof BADGE_THRESHOLDS)[number])
    ) {
      violations.push("badge_not_at_threshold");
    }
  }

  // One question at a time — at most one hot tile carrying chips.
  const hotQuestionTiles = plan.tiles.filter((t) => t.tone === "hot" && "chips" in t);
  if (hotQuestionTiles.length > 1) violations.push("multiple_hot_question_tiles");

  // Celebrations suppress ThanksCard until dismiss_celebration.
  const hasCelebration = plan.tiles.some((t) => t.component === "BadgeCelebrationCard");
  const hasThanks = plan.tiles.some((t) => t.component === "ThanksCard");
  if (hasCelebration && hasThanks) violations.push("celebration_suppresses_thanks");

  return violations;
}

/** The never-broken-screen fallback (§4.6): a calm all-clear stack. */
export function allClearPlan(planId: string, header: HomePlanHeader): HomePlan {
  return {
    planId,
    header,
    tiles: [
      {
        component: "AllClearCard",
        id: `${planId}-all-clear`,
        layout: LAYOUT_2x2,
        tone: "calm",
        props: {},
      },
    ],
    overlays: [],
  };
}

/** Shared copy constants — the LLM picks these, never writes them (§4.6-6). */
export const COPY = {
  reassurance: "Every answer counts the same.",
  thanksTitle: "Thanks for telling us!",
  thanksBody: "Your care team now has the full picture.",
  allClearTitle: "Nothing else is due today",
  allClearBody: "Your care team now has the full picture.",
  bookedLabel: "Booked by your care team",
} as const;
