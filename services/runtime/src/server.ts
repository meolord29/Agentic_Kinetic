import { createServer } from "node:http";
import { randomUUID } from "node:crypto";
import { CopilotRuntime, BuiltInAgent } from "@copilotkit/runtime/v2";
import { createCopilotNodeListener } from "@copilotkit/runtime/v2/node";
import { EventType, type BaseEvent } from "@ag-ui/core";
import { HomePlan, allClearPlan, validatePlan } from "@kinetic/ui-schema";
import { getSnapshot, healthz, close as closeDb } from "./db.js";
import { buildPlan } from "./planner.js";

const PORT = Number(process.env.PORT ?? 8200);
const DETERMINISTIC = process.env.PLANNER_MODE !== "llm"; // P0: deterministic-first

/**
 * ui_agent — emits `compose_home` as a frontend tool call (§4.3):
 *   ↓ UI     useFrontendTool({ name: "compose_home" }) on the device renders it
 *   ↑ state  the deterministic P0 planner reads the snapshot via the db module
 *            (Auth0-delegated `get_due_items` arrives in P1 — §3.2)
 */
const uiAgent = new BuiltInAgent({
  type: "custom",
  factory: async function* (ctx): AsyncGenerator<BaseEvent> {
    const started = Date.now();
    let plan: HomePlan;
    let violations: string[] = [];

    try {
      const snapshot = await getSnapshot();
      plan = buildPlan(snapshot);
      if (process.env.PLANNER_DEBUG === "1") {
        console.log("[ui_agent] snapshot:", JSON.stringify(snapshot.due));
      }
    } catch (err) {
      console.error("[ui_agent] snapshot failed — all-clear fallback:", err);
      plan = allClearPlan(`plan-error-${Date.now()}`, {
        greeting: "Hi, Elena",
        dateLabel: "",
        level: 1,
        levelPct: 0,
      });
    }

    const toolCallId = randomUUID();
    const args = JSON.stringify(plan);

    yield { type: EventType.TOOL_CALL_START, toolCallId, toolCallName: "compose_home" };
    // Stream the args in chunks like a model would (single chunk is legal).
    for (let i = 0; i < args.length; i += 512) {
      yield { type: EventType.TOOL_CALL_ARGS, toolCallId, delta: args.slice(i, i + 512) };
    }
    yield { type: EventType.TOOL_CALL_END, toolCallId };

    console.log(
      `[ui_agent] compose_home ${plan.planId} · ${plan.tiles.length} tiles · ${Date.now() - started}ms` +
        (violations.length ? ` · VIOLATIONS: ${violations.join(",")}` : ""),
    );
  },
} as ConstructorParameters<typeof BuiltInAgent>[0]);

const runtime = new CopilotRuntime({
  agents: { ui_agent: uiAgent },
});

const listener = createCopilotNodeListener({
  runtime,
  basePath: "/api/copilotkit",
});

const server = createServer((req, res) => {
  const url = req.url ?? "/";
  if (url === "/healthz" || url.startsWith("/healthz")) {
    healthz()
      .then((ok) => {
        res.writeHead(ok ? 200 : 503, { "content-type": "application/json" });
        res.end(JSON.stringify({ status: ok ? "ok" : "degraded", db: ok }));
      })
      .catch(() => {
        res.writeHead(503, { "content-type": "application/json" });
        res.end(JSON.stringify({ status: "down" }));
      });
    return;
  }
  listener(req, res);
});

server.listen(PORT, "0.0.0.0", () => {
  console.log(`[runtime] listening on :${PORT} (agent endpoint: /api/copilotkit, planner: ${DETERMINISTIC ? "deterministic" : "llm"})`);
});

async function shutdown() {
  server.close();
  await closeDb();
  process.exit(0);
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

// keep validators referenced (client double-checks too)
void validatePlan;
void HomePlan;
