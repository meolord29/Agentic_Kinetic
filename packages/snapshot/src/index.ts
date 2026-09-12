import { Pool, type PoolConfig } from "pg";
import {
  PatientContextSummary,
  type PatientContextSummary as PatientContextSummaryType,
} from "@kinetic/ui-schema";

/**
 * Shared read-side data module (§7.2/§7.3) — the single derivation of the
 * `PatientContextSummary` contract, consumed by BOTH the runtime planner
 * (direct-DB read path, user decision) and the data-api REST surface, so the
 * plan and the client context can never drift apart.
 *
 * No auth by design (§3.1): fixed demo user, least-privilege kinetic_agent role.
 * Server-side reward rules live here: `recentDoseAnswer` (drives ThanksCard.plus)
 * and `unlockPending` (threshold crossing within the celebration window) are
 * recomputed from DB timestamps, never taken from the client (§5.6).
 */

export const DEMO_USER_ID = "00000000-0000-4000-8000-0000000000e1";

/** §4.6-4: "within one plan of a dose answer" — the plus window. */
export const RECENT_WINDOW_MINUTES = 5;

export interface BadgeDef {
  n: number;
  label: string;
  copy: string;
}

/** Snapshot + the extra server-side facts the planner consumes. */
export interface KineticData {
  snapshot: PatientContextSummaryType;
  recentDoseAnswer: boolean;
  badgeDefs: BadgeDef[];
}

function daypartNow(timezone: string): "morning" | "evening" {
  const hour = Number(
    new Intl.DateTimeFormat("en-GB", { hour: "2-digit", hour12: false, timeZone: timezone }).format(new Date()),
  );
  return hour >= 12 ? "evening" : "morning";
}

const DATE_FMT = new Intl.DateTimeFormat("en-GB", {
  weekday: "long",
  day: "numeric",
  month: "long",
  timeZone: "UTC",
});

export function createSnapshotStore(config: { connectionString: string; max?: number }) {
  const pool = new Pool({ connectionString: config.connectionString, max: config.max ?? 5 });

  async function healthz(): Promise<boolean> {
    const r = await pool.query("SELECT 1");
    return r.rowCount === 1;
  }

  async function getData(): Promise<KineticData> {
    const userId = DEMO_USER_ID;

    const [userRes, stateRes, questionRes, tempRes, bookingRes, reminderRes, doseTodayRes, recentDoseRes, unlockRes, badgeDefsRes] =
      await Promise.all([
        pool.query(
          `SELECT display_name, language, timezone, registered_at FROM app.users WHERE id = $1`,
          [userId],
        ),
        pool.query(`SELECT checkins FROM app.gamification_state WHERE user_id = $1`, [userId]),
        pool.query(
          `SELECT text FROM app.care_questions
           WHERE user_id = $1 AND status = 'waiting' ORDER BY created_at DESC LIMIT 1`,
          [userId],
        ),
        pool.query(
          `SELECT reason FROM app.temperature_requests
           WHERE user_id = $1 AND fulfilled_at IS NULL AND cancelled_at IS NULL
           ORDER BY requested_at DESC LIMIT 1`,
          [userId],
        ),
        pool.query(
          `SELECT test_name, for_date, fasting FROM app.bookings
           WHERE user_id = $1 AND for_date >= current_date ORDER BY for_date ASC LIMIT 1`,
          [userId],
        ),
        pool.query(
          `SELECT id::text, kind, text FROM app.reminders
           WHERE user_id = $1 AND acked_at IS NULL ORDER BY fire_at ASC LIMIT 3`,
          [userId],
        ),
        pool.query(
          `SELECT 1 FROM app.checkins WHERE user_id = $1 AND dose_at::date = current_date LIMIT 1`,
          [userId],
        ),
        pool.query(
          `SELECT 1 FROM app.checkins
           WHERE user_id = $1 AND kind = 'dose' AND logged_at > now() - interval '5 minutes' LIMIT 1`,
          [userId],
        ),
        pool.query(
          `SELECT b.n, d.label FROM app.badges_earned b
           JOIN app.badge_defs d ON d.n = b.n
           WHERE b.user_id = $1 AND b.earned_at > now() - interval '5 minutes'
           ORDER BY b.earned_at DESC LIMIT 1`,
          [userId],
        ),
        pool.query(`SELECT n, label, copy FROM app.badge_defs ORDER BY n ASC`),
      ]);

    const user = userRes.rows[0];
    if (!user) throw new Error("demo user missing — run migrations/seed");
    const checkins: number = stateRes.rows[0]?.checkins ?? 0;

    const level = Math.floor(checkins / 25) + 1;
    const levelPct = Math.round(((checkins % 25) / 25) * 100);

    const badgeDefs: BadgeDef[] = badgeDefsRes.rows as BadgeDef[];
    const nextDef = badgeDefs.find((d) => d.n > checkins) ?? null;
    const unlock = unlockRes.rows[0] as { n: number; label: string } | undefined;

    const booking = bookingRes.rows[0] as
      | { test_name: string; for_date: string | Date; fasting: boolean }
      | undefined;
    const daypart = daypartNow(user.timezone);

    const snapshot = PatientContextSummary.parse({
      generatedAt: new Date().toISOString(),
      user: {
        displayName: user.display_name,
        daypart,
        dateLabel: DATE_FMT.format(new Date()),
        language: user.language,
        registered: user.registered_at !== null,
      },
      consent: { deidentifiedResearch: false },
      progress: {
        checkins,
        level,
        levelPct,
        nextBadge: nextDef
          ? { n: nextDef.n, label: nextDef.label, remaining: nextDef.n - checkins }
          : null,
        // §5.6: unlock is a server-side fact with a celebration window — never client-invented
        unlockPending: unlock ? { n: unlock.n, label: unlock.label } : null,
      },
      due: {
        dose: doseTodayRes.rowCount ? { status: "done", answer: "taken" } : { status: "due" },
        nextSample: booking
          ? {
              booked: true,
              when: DATE_FMT.format(new Date(booking.for_date)),
              tomorrow: new Date(booking.for_date).getTime() - new Date().setHours(0, 0, 0, 0) === 86400000,
              test: booking.test_name,
              fasting: booking.fasting,
            }
          : { booked: false, when: null, tomorrow: false, test: null, fasting: null },
        temperature: { due: tempRes.rowCount ? true : false, reason: tempRes.rows[0]?.reason ?? null },
        teamQuestion: {
          waiting: questionRes.rowCount ? true : false,
          text: questionRes.rows[0]?.text ?? null, // VERBATIM
        },
        medWatch: { active: false, step: null },
        vomitCheck: { waiting: false },
        reminders: (reminderRes.rows as { id: string; kind: string; text: string }[]).map((r) => ({
          id: r.id,
          kind: r.kind as "night_before_prep" | "checkin_nudge" | "booking_reminder",
          text: r.text,
        })),
      },
      pins: { handoff: false, diaryShared: false },
      tour: { completed: true, active: false },
    });

    return {
      snapshot,
      // §4.6-4 window: "within one plan of a dose answer"
      recentDoseAnswer: recentDoseRes.rowCount === 1,
      badgeDefs,
    };
  }

  async function getSnapshot(): Promise<PatientContextSummaryType> {
    return (await getData()).snapshot;
  }

  // Write-path passthroughs for the data-api (transactions, mutations). The
  // runtime never uses these — it is read-only by design (§3.2).
  function query<T extends import("pg").QueryResultRow = import("pg").QueryResultRow>(
    text: string,
    values?: unknown[],
  ) {
    return pool.query<T>(text, values);
  }
  function connect() {
    return pool.connect();
  }

  async function close(): Promise<void> {
    await pool.end();
  }

  return { healthz, getSnapshot, getData, query, connect, close };
}

export type SnapshotStore = ReturnType<typeof createSnapshotStore>;