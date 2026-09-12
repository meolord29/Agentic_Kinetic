import {
  BADGE_THRESHOLDS,
  COPY,
  LAYOUT_1x2,
  LAYOUT_2x2,
  LAYOUT_2x5,
  LAYOUT_STRIP,
  allClearPlan,
  validatePlan,
  type HomePlan,
  type PlanSnapshot,
  type Tile,
} from "@kinetic/ui-schema";
import type { KineticData } from "@kinetic/snapshot";

/**
 * Deterministic-first planner (P0/P1). The doc's settled posture is
 * "deterministic data, generative layout" — for P0 the layout is composed
 * deterministically from the snapshot and pushed through the SAME §4.6
 * validators an LLM plan would face. The LLM composer joins in a later phase
 * behind this identical contract.
 *
 * Reward facts (`recentDoseAnswer`, `unlockPending`) are server-side
 * derivations from DB timestamps (§5.6) — the client can never claim them.
 */
export function buildPlan({ snapshot, recentDoseAnswer, badgeDefs }: KineticData): HomePlan {
  const planId = `plan-${Date.now()}`;
  const header = {
    greeting: snapshot.user.daypart === "evening" ? `Good evening, ${snapshot.user.displayName}` : `Hi, ${snapshot.user.displayName}`,
    dateLabel: snapshot.user.dateLabel,
    level: snapshot.progress.level,
    levelPct: snapshot.progress.levelPct,
  };

  const tiles: Tile[] = [];
  const due = snapshot.due;
  const unlock = snapshot.progress.unlockPending;

  // Badge day (workflow-06): the celebration takes the hot slot. The validator
  // suppresses ThanksCard while a celebration shows — gate it here too.
  if (unlock) {
    const def = badgeDefs.find((d) => d.n === unlock.n);
    tiles.push({
      component: "BadgeCelebrationCard",
      id: `badge-${unlock.n}`,
      layout: LAYOUT_2x5,
      tone: "hot",
      props: {
        n: unlock.n,
        label: unlock.label,
        copy: def?.copy ?? "That is a clear picture for your care team.",
        shelf: BADGE_THRESHOLDS.map((n) => ({ n, earned: snapshot.progress.checkins >= n })),
      },
    });
  }

  if (due.dose.status === "due") {
    // Workflow-01: the dose question takes the hot slot (§4.6: one question at
    // a time — while the dose is due, the team question waits for the next
    // re-plan; the flush loop re-plans moments after the answer anyway).
    tiles.push({
      component: "DosePromptCard",
      id: "dose",
      layout: { cols: 2, rows: 3 },
      tone: "hot",
      props: { headline: "Time for your morning dose", reassurance: COPY.reassurance },
      chips: [
        { label: "Taken", action: { type: "answer_dose", value: "taken" } },
        { label: "Later", action: { type: "answer_dose", value: "late" } },
        { label: "Skipped it", action: { type: "answer_dose", value: "missed" } },
        { label: "Not sure", action: { type: "answer_dose", value: "not_sure" } },
      ],
    });
  }

  if (due.dose.status === "done") {
    tiles.push({
      component: "DoneRow",
      id: "done-dose",
      layout: LAYOUT_STRIP,
      tone: "done",
      props: { label: "Morning dose", status: "Logged" },
    });
  }

  if (due.dose.status !== "due" && due.teamQuestion.waiting && due.teamQuestion.text) {
    tiles.push({
      component: "TeamQuestionCard",
      id: "team-question",
      layout: LAYOUT_2x2,
      tone: "hot",
      props: { text: due.teamQuestion.text }, // VERBATIM — validator diffs this against the DB row
      chips: [
        { label: "Yes", action: { type: "answer_question", value: "yes" } },
        { label: "No", action: { type: "answer_question", value: "no" } },
        { label: "Not sure", action: { type: "answer_question", value: "not_sure" } },
      ],
    });
  }

  // The plus lives only inside the dose-answer window (§4.6-4) and never on a
  // celebration day (§4.6: celebration suppresses thanks).
  if (due.dose.status === "done" && recentDoseAnswer && !unlock) {
    const { nextBadge } = snapshot.progress;
    tiles.push({
      component: "ThanksCard",
      id: "thanks",
      layout: LAYOUT_2x2,
      tone: "good",
      props: {
        plus: true,
        progressText: nextBadge
          ? `${nextBadge.remaining} more check-in${nextBadge.remaining > 1 ? "s" : ""} to your next badge`
          : "Every check-in counts",
      },
    });
  }

  if (due.temperature.due) {
    tiles.push({
      component: "TemperatureCard",
      id: "temperature",
      layout: { cols: 1, rows: 4 },
      tone: "hot",
      props: { reason: due.temperature.reason ?? "scheduled" },
      chips: [
        { label: "36.5 °C", action: { type: "answer_temperature", value: "v36_5" } },
        { label: "37.0 °C", action: { type: "answer_temperature", value: "v37_0" } },
        { label: "37.5 °C", action: { type: "answer_temperature", value: "v37_5" } },
        { label: "38 °C +", action: { type: "answer_temperature", value: "v38_plus" } },
        { label: "Didn't measure", action: { type: "answer_temperature", value: "not_measured" } },
      ],
    });
  }

  if (due.nextSample.booked && due.nextSample.tomorrow) {
    tiles.push({
      component: "SamplePrepCard",
      id: "sample-prep",
      layout: { cols: 2, rows: 3 },
      tone: "hot",
      props: {
        when: due.nextSample.when ?? "tomorrow",
        stops: ["Before dose", "1 h", "3 h", "6 h"],
        notes: due.nextSample.fasting ? "Fasting. I'll walk you through each one." : "I'll walk you through each one.",
      },
    });
  }

  tiles.push({
    component: "BadgesSquare",
    id: "badges",
    layout: LAYOUT_1x2,
    tone: "game",
    props: {
      progressText: snapshot.progress.nextBadge
        ? `${snapshot.progress.nextBadge.remaining} more check-in${snapshot.progress.nextBadge.remaining > 1 ? "s" : ""}`
        : "Every check-in counts",
    },
  });

  tiles.push({
    component: "CareTeamSquare",
    id: "care-team",
    layout: LAYOUT_1x2,
    tone: "calm",
    props: {},
  });

  for (const reminder of due.reminders.slice(0, 2)) {
    tiles.push({
      component: "ReminderStrip",
      id: `reminder-${reminder.id}`,
      layout: LAYOUT_STRIP,
      tone: "info",
      props: { text: reminder.text },
    });
  }

  // Workflow-09 all-clear: nothing due anywhere (prototype reg weight −1).
  // Done rows coexist with the all-clear card ("All logged") — they are not
  // due items, matching the prototype's `when` exactly.
  const nothingDue =
    due.dose.status !== "due" &&
    !due.teamQuestion.waiting &&
    !due.temperature.due &&
    !(due.nextSample.booked && due.nextSample.tomorrow) &&
    !recentDoseAnswer &&
    !unlock;

  if (nothingDue) {
    tiles.unshift({
      component: "AllClearCard",
      id: "all-clear",
      layout: LAYOUT_2x2,
      tone: "calm",
      props: {},
    });
  }

  const plan: HomePlan = { planId, header, tiles, overlays: [] };

  // §4.6 guardrails: the deterministic planner faces the same validators an
  // LLM plan would. Any violation → all-clear fallback (never a broken screen).
  const snap: PlanSnapshot = { context: snapshot, recentDoseAnswer };
  const violations = validatePlan(plan, snap);
  if (violations.length > 0) {
    console.error("[planner] plan violations — falling back to all-clear:", violations, JSON.stringify(tiles));
    return allClearPlan(planId, header);
  }
  return plan;
}

export { COPY };