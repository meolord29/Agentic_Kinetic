import Fastify from "fastify";
import { Pool } from "pg";

/**
 * data-api (P0 skeleton). P0 runs no-auth: no JWKS verify, no scope checks —
 * those land with Auth0 in P1 (§3). Endpoints declare their returned fields
 * (minimum-necessary discipline starts now).
 */

const DEMO_USER_ID = "00000000-0000-4000-8000-0000000000e1";

const pool = new Pool({ connectionString: process.env.DATABASE_URL, max: 5 });
const app = Fastify({ logger: true });

app.get("/healthz", async () => {
  const r = await pool.query("SELECT 1");
  return { status: r.rowCount === 1 ? "ok" : "degraded" };
});

app.get("/me/snapshot", async () => {
  const [userRes, stateRes] = await Promise.all([
    pool.query(`SELECT display_name, language, timezone FROM app.users WHERE id = $1`, [DEMO_USER_ID]),
    pool.query(`SELECT checkins FROM app.gamification_state WHERE user_id = $1`, [DEMO_USER_ID]),
  ]);
  const user = userRes.rows[0];
  const checkins = stateRes.rows[0]?.checkins ?? 0;
  return {
    user: user
      ? { displayName: user.display_name, language: user.language, timezone: user.timezone }
      : null,
    progress: { checkins, level: Math.floor(checkins / 25) + 1 },
  };
});

const port = Number(process.env.PORT ?? 8080);
app.listen({ port, host: "0.0.0.0" }).catch((err) => {
  app.log.error(err);
  process.exit(1);
});

async function shutdown() {
  await app.close();
  await pool.end();
  process.exit(0);
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
