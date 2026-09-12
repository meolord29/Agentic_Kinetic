import { Pool } from "pg";
import {
  BADGE_THRESHOLDS,
  type PatientContextSummary,
} from "@kinetic/ui-schema";

/**
 * P0 db module (user decision: the agent talks to Postgres directly with the
 * least-privilege kinetic_agent role; user auth dropped entirely — single-user
 * local demo, §3.1). Fixed demo patient — no bearer token, no auth provider.
 */
const DEMO_USER_ID = "00000000-0000-4000-8000-0000000000e1";

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  max: 5,
});

export async function healthz(): Promise<boolean> {
  const r = await pool.query("SELECT 1");
  return r.rowCount === 1;
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

export async function getSnapshot(): Promise<PatientContextSummary> {
  const userId = DEMO_USER_ID;

  const [userRes, stateRes, questionRes, tempRes, bookingRes, reminderRes] = await Promise.all([
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
  ]);

  const user = userRes.rows[0];
  if (!user) throw new Error("demo user missing — run migrations/seed");
  const checkins: number = stateRes.rows[0]?.checkins ?? 0;

  const level = Math.floor(checkins / 25) + 1;
  const levelPct = Math.round(((checkins % 25) / 25) * 100);
  const nextN = BADGE_THRESHOLDS.find((n) => n > checkins) ?? null;

  // P0 dose rule: due if no dose check-in logged today.
  const doseToday = await pool.query(
    `SELECT 1 FROM app.checkins WHERE user_id = $1 AND dose_at::date = current_date LIMIT 1`,
    [userId],
  );

  const booking = bookingRes.rows[0];
  const daypart = daypartNow(user.timezone);

  return {
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
      nextBadge: nextN
        ? { n: nextN, label: `First ${nextN === 7 ? "week" : nextN === 30 ? "month" : nextN === 100 ? "hundred" : "year"}`, remaining: nextN - checkins }
        : null,
      unlockPending: null,
    },
    due: {
      dose: doseToday.rowCount ? { status: "done", answer: "taken" } : { status: "due" },
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
      reminders: reminderRes.rows.map((r: { id: string; kind: string; text: string }) => ({
        id: r.id,
        kind: r.kind as "night_before_prep" | "checkin_nudge" | "booking_reminder",
        text: r.text,
      })),
    },
    pins: { handoff: false, diaryShared: false },
    tour: { completed: true, active: false },
  };
}

export async function close(): Promise<void> {
  await pool.end();
}
