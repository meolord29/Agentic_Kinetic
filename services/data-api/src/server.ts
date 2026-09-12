import Fastify from "fastify";
import { z } from "zod";
import { BADGE_THRESHOLDS } from "@kinetic/ui-schema";
import { createSnapshotStore, DEMO_USER_ID } from "@kinetic/snapshot";

/**
 * data-api (P1) — the app-facing REST surface (§7). No user auth by design
 * (§3.1): every request is attributed to the fixed demo user, the loopback
 * binding is the boundary, and each endpoint declares its returned fields —
 * one audit row per request, written by the same helper (§3.4).
 *
 * Reads go through the shared `@kinetic/snapshot` module so the planner and
 * the client see byte-identical context. The ONLY path that increments
 * `checkins` is POST /me/checkins, inside one transaction with the
 * badge-threshold eval (§7.3); retries dedup on client_event_id (§5.6).
 */

const store = createSnapshotStore({ connectionString: process.env.DATABASE_URL ?? "", max: 5 });
const app = Fastify({ logger: true });

// -- request schemas (built on the contract's closed enums) ------------------

const CheckinBody = z.object({
  answer: z.enum(["taken", "late", "missed", "not_sure"]),
  eventId: z.string().uuid(),
  doseAt: z.string().datetime().optional(),
});

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
]);

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
  const { kind, value, eventId } = parsed.data;

  if (kind === "question") {
    // Idempotent by the status machine (§7.3): waiting → answered, monotonic.
    // Retries (same or different eventId) land as no-op — the verbatim row is
    // never answered twice, and the first honest answer wins.
    const r = await store.query(
      `UPDATE app.care_questions
       SET status = 'answered', answer = $2, answered_at = now()
       WHERE user_id = $1 AND status = 'waiting'
       RETURNING id::text`,
      [DEMO_USER_ID, value],
    );
    await audit("answers.create", ["kind", "value"], `question answer ${eventId}`);
    return { status: r.rowCount ? "ok" : "noop", kind };
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
    [DEMO_USER_ID, value, reason, eventId],
  );
  if (openRow) {
    await store.query(`UPDATE app.temperature_requests SET fulfilled_at = now() WHERE id = $1`, [openRow.id]);
  }
  await audit("answers.create", ["kind", "value", "reason"], `temperature answer ${eventId}`);
  return { status: "ok", kind };
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