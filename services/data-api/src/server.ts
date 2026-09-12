import Fastify from "fastify";
import { z } from "zod";
import { BADGE_THRESHOLDS, SYMPTOM_LABELS } from "@kinetic/ui-schema";
import { createSnapshotStore, DEMO_USER_ID } from "@kinetic/snapshot";

/**
 * data-api (P1+P3) — the app-facing REST surface (§7). No user auth by design
 * (§3.1): every request is attributed to the fixed demo user, the loopback
 * binding is the boundary, and each endpoint declares its returned fields —
 * one audit row per request, written by the same helper (§3.4).
 *
 * Reads go through the shared `@kinetic/snapshot` module so the planner and
 * the client see byte-identical context. The ONLY path that increments
 * `checkins` is POST /me/checkins, inside one transaction with the
 * badge-threshold eval (§7.3); retries dedup on client_event_id (§5.6).
 * P3: sick-day/diary/handoff commits NEVER touch checkins (workflows
 * 08/12 §6 — no +1, no badges while she feels unwell).
 */

const store = createSnapshotStore({ connectionString: process.env.DATABASE_URL ?? "", max: 5 });
const app = Fastify({ logger: true });

// -- request schemas (built on the contract's closed enums) ------------------

const CheckinBody = z.object({
  answer: z.enum(["taken", "late", "missed", "not_sure"]),
  eventId: z.string().uuid(),
  doseAt: z.string().datetime().optional(),
});

const KNOWN_LABELS = SYMPTOM_LABELS as unknown as readonly string[];

const AnswerBody = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("question"),
    value: z.enum(["yes", "no", "not_sure"]),
    eventId: z.string().uuid(),
  }),
  z.object({
    kind: z.literal("temperature"),
    value: z.enum(["v36_5", "v37_0", "v37_5", "v38_plus", "not_measured"]),
    eventId: z.string().uuid(),
  }),
  z.object({
    kind: z.literal("vomit"),
    value: z.enum(["within_hour", "later", "didnt_take"]),
    eventId: z.string().uuid(),
  }),
  z.object({
    kind: z.literal("symptoms"),
    labels: z.array(z.enum(SYMPTOM_LABELS as unknown as [string, ...string[]])).min(1).max(9),
    transcript: z.string().max(2000).optional(),
    eventId: z.string().uuid(),
  }),
  z.object({
    kind: z.literal("diary"),
    text: z.string().min(1).max(2000),
    noted: z.array(z.string()).max(9).default([]),
    eventId: z.string().uuid(),
  }),
]);

const HandoffBody = z.object({
  text: z.string().min(1).max(500),
  transcript: z.string().max(2000).optional(),
  eventId: z.string().uuid(),
});

// -- audit (§3.4): one row per request, fields declared per endpoint ----------

async function audit(action: string, fields: string[], purpose: string) {
  await store.query(
    `INSERT INTO app.audit_log (actor_type, actor_id, user_id, action, fields, purpose)
     VALUES ('user', $1::text, $1::uuid, $2, $3, $4)`,
    [DEMO_USER_ID, action, fields, purpose],
  );
}

// -- routes -------------------------------------------------------------------

app.get("/healthz", async () => {
  const ok = await store.healthz();
  return { status: ok ? "ok" : "degraded" };
});

app.get("/me/snapshot", async (_req, reply) => {
  try {
    const snapshot = await store.getSnapshot();
    await audit("snapshot.read", ["user", "consent", "progress", "due", "pins", "tour"], "app snapshot sync");
    return snapshot;
  } catch (err) {
    app.log.error(err);
    return reply.code(503).send({ error: "snapshot unavailable" });
  }
});

app.post("/me/checkins", async (req, reply) => {
  const parsed = CheckinBody.safeParse(req.body);
  if (!parsed.success) return reply.code(400).send({ error: "invalid body", issues: parsed.error.issues });
  const { answer, eventId, doseAt } = parsed.data;

  const client = await store.connect();
  try {
    await client.query("BEGIN");
    const ins = await client.query(
      `INSERT INTO app.checkins (user_id, kind, answer, dose_at, client_event_id)
       VALUES ($1, 'dose', $2, COALESCE($3::timestamptz, now()), $4)
       ON CONFLICT (client_event_id) DO NOTHING RETURNING id`,
      [DEMO_USER_ID, answer, doseAt ?? null, eventId],
    );
    if (ins.rowCount === 0) {
      await client.query("COMMIT");
      await audit("checkins.dedup", ["eventId"], "patient check-in retry (§5.6)");
      return { status: "deduped" };
    }

    // §7.3 rule 1: only this endpoint increments checkins — one transaction
    // with the badge-threshold eval, recomputed server-side.
    const upd = await client.query(
      `UPDATE app.gamification_state SET checkins = checkins + 1, updated_at = now()
       WHERE user_id = $1 RETURNING checkins`,
      [DEMO_USER_ID],
    );
    const checkins: number = upd.rows[0].checkins;

    let unlock: { n: number; label: string } | null = null;
    if (BADGE_THRESHOLDS.includes(checkins as (typeof BADGE_THRESHOLDS)[number])) {
      const def = await client.query(`SELECT label FROM app.badge_defs WHERE n = $1`, [checkins]);
      await client.query(`INSERT INTO app.badges_earned (user_id, n) VALUES ($1, $2)`, [DEMO_USER_ID, checkins]);
      unlock = { n: checkins, label: def.rows[0]?.label ?? `Badge ${checkins}` };
    }

    await client.query("COMMIT");
    await audit("checkins.create", ["answer", "checkins", "unlock"], "patient check-in");
    return { status: "ok", checkins, unlock };
  } catch (err) {
    await client.query("ROLLBACK");
    throw err;
  } finally {
    client.release();
  }
});

app.post("/me/answers", async (req, reply) => {
  const parsed = AnswerBody.safeParse(req.body);
  if (!parsed.success) return reply.code(400).send({ error: "invalid body", issues: parsed.error.issues });
  const body = parsed.data;
  const { kind, eventId } = body;

  if (kind === "question") {
    // Idempotent by the status machine (§7.3): waiting → answered, monotonic.
    // Retries (same or different eventId) land as no-op — the verbatim row is
    // never answered twice, and the first honest answer wins.
    const r = await store.query(
      `UPDATE app.care_questions
       SET status = 'answered', answer = $2, answered_at = now()
       WHERE user_id = $1 AND status = 'waiting'
       RETURNING id::text`,
      [DEMO_USER_ID, body.value],
    );
    await audit("answers.create", ["kind", "value"], `question answer ${eventId}`);
    return { status: r.rowCount ? "ok" : "noop", kind };
  }

  if (kind === "vomit") {
    const r = await store.query(
      `INSERT INTO app.vomit_answers (user_id, answer, client_event_id)
       VALUES ($1, $2, $3)
       ON CONFLICT (client_event_id) DO NOTHING RETURNING id::text`,
      [DEMO_USER_ID, body.value, eventId],
    );
    await audit("answers.create", ["kind", "value"], `vomit-check answer ${eventId}`);
    return { status: r.rowCount ? "ok" : "deduped", kind };
  }

  if (kind === "symptoms") {
    // Workflow-08 confirm ("Looks right"): log the labels, store the verbatim
    // transcript as a voice note, and derive the scripted chains server-side —
    // fever/flu-like opens a sick-day temperature request (workflow-05); the
    // vomit check simply waits while a Nausea/Vomiting log is unanswered.
    // Chain triggers come from the CONFIRMED labels, never from free text.
      const client = await store.connect();
      let fresh = false;
      try {
        await client.query("BEGIN");
        const ins = await client.query(
          `INSERT INTO app.symptom_logs (user_id, labels, client_event_id)
           VALUES ($1, $2, $3)
           ON CONFLICT (client_event_id) DO NOTHING RETURNING id::text`,
          [DEMO_USER_ID, body.labels, eventId],
        );
        fresh = (ins.rowCount ?? 0) > 0;
        if (body.transcript) {
          await client.query(
            `INSERT INTO app.voice_notes (user_id, kind, transcript, noted, client_event_id)
             VALUES ($1, 'sick', $2, $3::jsonb, $4)
             ON CONFLICT (client_event_id) DO NOTHING`,
            [DEMO_USER_ID, body.transcript, JSON.stringify(body.labels), `${eventId}-note`],
          );
        }
        if (body.labels.some((l) => l === "Fever" || l === "Flu-like")) {
          const open = await client.query(
            `SELECT 1 FROM app.temperature_requests
             WHERE user_id = $1 AND fulfilled_at IS NULL AND cancelled_at IS NULL LIMIT 1`,
            [DEMO_USER_ID],
          );
          if (open.rowCount === 0) {
            await client.query(
              `INSERT INTO app.temperature_requests (user_id, reason) VALUES ($1, 'sick_day')`,
              [DEMO_USER_ID],
            );
          }
        }
        await client.query("COMMIT");
      } catch (err) {
        await client.query("ROLLBACK");
        throw err;
      } finally {
        client.release();
      }
      await audit("answers.create", ["kind", "labels"], `sick-day symptom confirm ${eventId}`);
      return { status: fresh ? "ok" : "deduped", kind };
    }

  if (kind === "diary") {
    // Workflow-12: share VERBATIM; never a check-in (no gamification_state touch).
    const client = await store.connect();
    try {
      await client.query("BEGIN");
      await client.query(
        `INSERT INTO app.diary_entries (user_id, text, noted, client_event_id)
         VALUES ($1, $2, $3, $4)
         ON CONFLICT (client_event_id) DO NOTHING`,
        [DEMO_USER_ID, body.text, body.noted, eventId],
      );
      await client.query(
        `INSERT INTO app.voice_notes (user_id, kind, transcript, noted, client_event_id)
         VALUES ($1, 'diary', $2, $3::jsonb, $4)
         ON CONFLICT (client_event_id) DO NOTHING`,
        [DEMO_USER_ID, body.text, JSON.stringify(body.noted), `${eventId}-note`],
      );
      await client.query("COMMIT");
    } catch (err) {
      await client.query("ROLLBACK");
      throw err;
    } finally {
      client.release();
    }
    await audit("answers.create", ["kind", "noted"], `diary share ${eventId}`);
    return { status: "ok", kind };
  }

  // temperature: record the reading, fulfill the open request if one exists.
  const open = await store.query(
    `SELECT id, reason FROM app.temperature_requests
     WHERE user_id = $1 AND fulfilled_at IS NULL AND cancelled_at IS NULL
     ORDER BY requested_at DESC LIMIT 1`,
    [DEMO_USER_ID],
  );
  const openRow = open.rows[0] as { id: string; reason: string } | undefined;
  const reason = openRow?.reason ?? "scheduled";
  await store.query(
    `INSERT INTO app.temperature_readings (user_id, bucket, reason, client_event_id)
     VALUES ($1, $2, $3, $4)
     ON CONFLICT (client_event_id) DO NOTHING`,
    [DEMO_USER_ID, body.value, reason, eventId],
  );
  if (openRow) {
    await store.query(`UPDATE app.temperature_requests SET fulfilled_at = now() WHERE id = $1`, [openRow.id]);
  }
  await audit("answers.create", ["kind", "value", "reason"], `temperature answer ${eventId}`);
  return { status: "ok", kind };
});

app.post("/me/handoffs", async (req, reply) => {
  const parsed = HandoffBody.safeParse(req.body);
  if (!parsed.success) return reply.code(400).send({ error: "invalid body", issues: parsed.error.issues });
  const { text, transcript, eventId } = parsed.data;
  // Workflow-07/11: the patient's words are relayed VERBATIM — no rewriting.
  const client = await store.connect();
  try {
    await client.query("BEGIN");
    const ins = await client.query(
      `INSERT INTO app.handoffs (user_id, question, client_event_id)
       VALUES ($1, $2, $3)
       ON CONFLICT (client_event_id) DO NOTHING RETURNING id::text`,
      [DEMO_USER_ID, text, eventId],
    );
    if (transcript) {
      await client.query(
        `INSERT INTO app.voice_notes (user_id, kind, transcript, client_event_id)
         VALUES ($1, 'health', $2, $3)
         ON CONFLICT (client_event_id) DO NOTHING`,
        [DEMO_USER_ID, transcript, `${eventId}-note`],
      );
    }
    await client.query("COMMIT");
    await audit("handoffs.create", ["text"], `care-team handoff ${eventId}`);
    return { status: ins.rowCount ? "ok" : "deduped" };
  } catch (err) {
    await client.query("ROLLBACK");
    throw err;
  } finally {
    client.release();
  }
});

app.post("/me/reminders/:id/ack", async (req, reply) => {
  const { id } = req.params as { id: string };
  if (!/^[0-9a-f-]{36}$/i.test(id)) return reply.code(400).send({ error: "invalid id" });
  const r = await store.query(
    `UPDATE app.reminders SET acked_at = now() WHERE id = $1 AND user_id = $2 AND acked_at IS NULL`,
    [id, DEMO_USER_ID],
  );
  await audit("reminders.ack", ["id"], "reminder acknowledgement");
  return { status: r.rowCount ? "ok" : "noop", id };
});

// -- dev-only demo harness (§5.5): reseed the demo user into a scenario state --
// Loopback-bound local demo (§3.1); every reseed writes one audit row like any
// other request. Scenarios cover the P2 demo walk (morning, question, badge,
// clear) and the P3 voice chains (health/sick/diary — workflows 07/08/12).

const SCENARIOS = ["morning", "question", "badge", "clear", "health", "sick", "diary"] as const;
const QUESTION_VERBATIM = "Did you start any new medicine this week?";
const SICK_SAID = "I feel nauseous, I've been sleeping most of the morning, and I think I have a fever.";
const SICK_LABELS = ["Nausea", "Tired", "Fever"];
const DIARY_SAID =
  "It's been a rough couple of days. I felt dizzy after my morning pill on Tuesday, I started taking a herbal supplement my friend gave me, and I haven't been sleeping well.";
const DIARY_NOTED = ["Dizzy", "Tired"];

app.post("/dev/scenario/:name", async (req, reply) => {
  const { name } = req.params as { name: string };
  if (!(SCENARIOS as readonly string[]).includes(name)) {
    return reply.code(400).send({ error: `unknown scenario — one of ${SCENARIOS.join(", ")}` });
  }
  const checkins = name === "badge" ? 99 : 31;
  const doseDone = name !== "morning"; // logged 2h ago → outside the plus window

  const client = await store.connect();
  try {
    await client.query("BEGIN");
    // Reseed via UPDATE/UPSERT only — the kinetic_agent role is
    // least-privilege (§3.3: no DELETE), so instead of wiping rows we move
    // them out of every window the snapshot derivation (§7.2) reads:
    // today's checkins → yesterday (dose due again, plus window closed),
    // fresh badge unlocks → out of the 5-minute celebration window,
    // open requests/questions/reminders → fulfilled/answered/acked.
    await client.query(
      `UPDATE app.checkins SET dose_at = dose_at - interval '1 day', logged_at = logged_at - interval '1 day'
       WHERE user_id = $1 AND dose_at::date = current_date`,
      [DEMO_USER_ID],
    );
    await client.query(
      `UPDATE app.badges_earned SET earned_at = earned_at - interval '1 hour'
       WHERE user_id = $1 AND earned_at > now() - interval '5 minutes'`,
      [DEMO_USER_ID],
    );
    await client.query(
      `UPDATE app.temperature_requests SET cancelled_at = now()
       WHERE user_id = $1 AND fulfilled_at IS NULL AND cancelled_at IS NULL`,
      [DEMO_USER_ID],
    );
    await client.query(
      `UPDATE app.care_questions SET status = 'answered', answered_at = now()
       WHERE user_id = $1 AND status = 'waiting'`,
      [DEMO_USER_ID],
    );
    await client.query(
      `UPDATE app.reminders SET acked_at = now() WHERE user_id = $1 AND acked_at IS NULL`,
      [DEMO_USER_ID],
    );
    // P3 chains: close open handoffs/diary pins; resolve a waiting vomit check
    // (fresh answer closes the chain); age symptom logs and diary entries out
    // of the today/24 h derivation windows so every scenario starts clean.
    await client.query(
      `UPDATE app.handoffs SET replied_at = now()
       WHERE user_id = $1 AND replied_at IS NULL`,
      [DEMO_USER_ID],
    );
    await client.query(
      // Aged 2 h back — inside one transaction `now()` is constant, so a
      // fresh symptom log (same transaction) must be strictly later than
      // this answer for the vomit-waiting derivation to see it (§7.2).
      `INSERT INTO app.vomit_answers (user_id, answer, answered_at, client_event_id)
       VALUES ($1, 'later', now() - interval '2 hours', 'seed-vomit-clear')
       ON CONFLICT (client_event_id) DO UPDATE SET answered_at = now() - interval '2 hours'`,
      [DEMO_USER_ID],
    );
    await client.query(
      `UPDATE app.symptom_logs SET logged_at = logged_at - interval '1 day'
       WHERE user_id = $1 AND logged_at > current_date`,
      [DEMO_USER_ID],
    );
    await client.query(
      `UPDATE app.diary_entries SET created_at = created_at - interval '1 day'
       WHERE user_id = $1 AND created_at > now() - interval '24 hours'`,
      [DEMO_USER_ID],
    );
    await client.query(
      `UPDATE app.voice_notes SET logged_at = logged_at - interval '1 day'
       WHERE user_id = $1 AND logged_at > now() - interval '5 minutes'`,
      [DEMO_USER_ID],
    );
    await client.query(
      `INSERT INTO app.gamification_state (user_id, checkins) VALUES ($1, $2)
       ON CONFLICT (user_id) DO UPDATE SET checkins = $2, updated_at = now()`,
      [DEMO_USER_ID, checkins],
    );
    if (doseDone) {
      // Idempotent seed row (stable client_event_id) — dose done 2h ago.
      await client.query(
        `INSERT INTO app.checkins (user_id, kind, answer, dose_at, logged_at, client_event_id)
         VALUES ($1, 'dose', 'taken', now() - interval '2 hours', now() - interval '2 hours', 'seed-dose')
         ON CONFLICT (client_event_id) DO UPDATE
         SET dose_at = now() - interval '2 hours', logged_at = now() - interval '2 hours'`,
        [DEMO_USER_ID],
      );
    }
    if (name === "question") {
      await client.query(
        `INSERT INTO app.care_questions (user_id, text, status) VALUES ($1, $2, 'waiting')`,
        [DEMO_USER_ID, QUESTION_VERBATIM],
      );
    }
    if (name === "sick") {
      // Workflow-08 post-confirm state (as if the voice note was just confirmed):
      // symptom log fresh (thanks flash, no +1) · vomit check waiting · sick-day
      // temperature request open (fires after the vomit answer, §08 flow 4→5).
      await client.query(
        `INSERT INTO app.symptom_logs (user_id, labels, client_event_id)
         VALUES ($1, $2, 'seed-sick')
         ON CONFLICT (client_event_id) DO UPDATE SET logged_at = now()`,
        [DEMO_USER_ID, SICK_LABELS],
      );
      await client.query(
        `INSERT INTO app.voice_notes (user_id, kind, transcript, noted, client_event_id)
         VALUES ($1, 'sick', $2, $3::jsonb, 'seed-sick-note')
         ON CONFLICT (client_event_id) DO UPDATE SET logged_at = now()`,
        [DEMO_USER_ID, SICK_SAID, JSON.stringify(SICK_LABELS)],
      );
      await client.query(
        `INSERT INTO app.temperature_requests (user_id, reason) VALUES ($1, 'sick_day')`,
        [DEMO_USER_ID],
      );
    }
    if (name === "diary") {
      await client.query(
        `INSERT INTO app.diary_entries (user_id, text, noted, client_event_id)
         VALUES ($1, $2, $3, 'seed-diary')
         ON CONFLICT (client_event_id) DO UPDATE SET created_at = now()`,
        [DEMO_USER_ID, DIARY_SAID, DIARY_NOTED],
      );
      await client.query(
        `INSERT INTO app.voice_notes (user_id, kind, transcript, noted, client_event_id)
         VALUES ($1, 'diary', $2, $3::jsonb, 'seed-diary-note')
         ON CONFLICT (client_event_id) DO UPDATE SET logged_at = now()`,
        [DEMO_USER_ID, DIARY_SAID, JSON.stringify(DIARY_NOTED)],
      );
    }
    // `health` seeds nothing extra: the handoff is created by the voice flow
    // itself (workflow-07) — hold-to-talk → confirm → POST /me/handoffs.
    await client.query("COMMIT");
    await audit("scenario.seed", ["name", "checkins"], `dev scenario reseed: ${name}`);
    return { status: "ok", scenario: name, checkins };
  } catch (err) {
    await client.query("ROLLBACK");
    throw err;
  } finally {
    client.release();
  }
});

const port = Number(process.env.PORT ?? 8080);
app.listen({ port, host: "0.0.0.0" }).catch((err) => {
  app.log.error(err);
  process.exit(1);
});

async function shutdown() {
  await app.close();
  await store.close();
  process.exit(0);
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);