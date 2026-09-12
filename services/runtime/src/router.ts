import { randomUUID } from "node:crypto";
import { BuiltInAgent } from "@copilotkit/runtime/v2";
import { COMMAND_WORKFLOWS, Overlay, SYMPTOM_LABELS } from "@kinetic/ui-schema";
import { EventType, type BaseEvent } from "@ag-ui/core";

/**
 * router (§6.2) — transcript classifier + confirm-before-act driver.
 *
 * The user decision for P3: LLM classification, no deterministic fallback —
 * every request goes to the model in the .env file (MODEL_ID +
 * OPENROUTER_API_KEY, an OpenAI-compatible endpoint; OPENROUTER_BASE_URL
 * overrides the host). We call chat completions directly instead of the
 * BuiltInAgent classic path because OpenRouter slugs ("anthropic/…",
 * "meta-llama/…") don't map onto the AI SDK's provider prefixes.
 *
 * The LLM only CLASSIFIES and extracts typed labels; `said` is filled here
 * from the verbatim input transcript, so the wire can never paraphrase her
 * words (workflows 07/08/12 §6). The emitted overlay is validated against the
 * ui-schema before streaming; one retry, then the conservative
 * command_unmatched fallback (workflow-11: honest refusal → care-team handoff
 * offer). The router never writes to the DB — commits happen only after the
 * patient taps "Looks right".
 */

const MODEL_ID = process.env.MODEL_ID ?? "";
const API_KEY = process.env.OPENROUTER_API_KEY ?? "";
const BASE_URL = process.env.OPENROUTER_BASE_URL ?? "https://openrouter.ai/api/v1";
const MAX_STEPS = 3; // §6.2: router runs can't linger

const SYSTEM_PROMPT = `You are the router of a patient health app (research prototype, single demo patient "Elena").
Classify the user's spoken-or-typed note into EXACTLY ONE variant and reply with JSON ONLY, no prose:

{"variant":"dose|health|sick|diary|command_matched|command_unmatched","workflow":"tour|dose|temperature|samples|badges|diary|call|message|null","noted":[{"label":"...","value":"...","changeable":true}]}

Rules (never break them):
1. SICK — the user describes feeling unwell (symptoms, illness). "noted" = one row per detected symptom, label from the closed list [${SYMPTOM_LABELS.join(", ")}], label field "Feeling", value = comma-joined labels, changeable true. Use ONLY labels from the list.
2. HEALTH — the user asks a clinical/medication question ("can I take…", "should I…"). NEVER answer it; classification is the whole job. "noted" = [].
3. DIARY — the user shares a personal story/status (how days have been, what happened). "noted" = rows: "Feeling" → detected symptom labels from the closed list (or omit), "Medicine" → short phrase if they mention starting/taking a medicine or supplement (changeable true), "Question" → "yes" if the entry contains a question for the team. Use ONLY labels from the closed list for symptoms.
4. DOSE — the note is about taking/logging the morning dose. "noted" = [{"label":"Dose","value":"taken|late|missed|not_sure","changeable":true}].
5. COMMAND_MATCHED — the user asks the app to DO something. Pick "workflow" from [${COMMAND_WORKFLOWS.join(", ")}]: tour (show me around), dose (log my dose), temperature (log temperature/fever check), samples (blood samples/fasting/appointment), badges (badges/level/progress), diary (write in diary/note something down/share something), call (call my care team), message (message my doctor/I have a question). "noted" = [{"label":"Workflow","value":"<workflow id>","changeable":false}].
6. COMMAND_UNMATCHED — a request that matches no workflow ("book me a taxi"). "workflow" = null, "noted" = [].
7. When in doubt between HEALTH and anything else, choose HEALTH (handoff to the human care team — the agent never answers clinical questions, never diagnoses, never advises).
8. Never include the transcript in your reply; never paraphrase it; reply with the JSON object and nothing else.`;

interface RouterDecision {
  variant: "dose" | "health" | "sick" | "diary" | "command_matched" | "command_unmatched";
  workflow: string | null;
  noted: { label: string; value: string; changeable: boolean }[];
}

function extractLastUserTranscript(input: unknown): string {
  const messages = (input as { messages?: { role?: string; content?: unknown }[] })?.messages ?? [];
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m?.role !== "user") continue;
    if (typeof m.content === "string") return m.content;
    if (Array.isArray(m.content)) {
      const text = m.content
        .map((p) => (p && typeof p === "object" && "text" in p ? String((p as { text?: string }).text ?? "") : ""))
        .join(" ")
        .trim();
      if (text) return text;
    }
  }
  return "";
}

function sanitizeDecision(raw: unknown, transcript: string): Overlay | null {
  const d = raw as Partial<RouterDecision> | null;
  if (!d || typeof d !== "object") return null;
  const known = new Set<string>(SYMPTOM_LABELS);
  const variant = d.variant;
  if (
    variant !== "dose" &&
    variant !== "health" &&
    variant !== "sick" &&
    variant !== "diary" &&
    variant !== "command_matched" &&
    variant !== "command_unmatched"
  ) {
    return null;
  }
  const workflow =
    typeof d.workflow === "string" && (COMMAND_WORKFLOWS as readonly string[]).includes(d.workflow)
      ? d.workflow
      : null;
  const noted = Array.isArray(d.noted)
    ? d.noted
        .filter((n) => n && typeof n.label === "string" && typeof n.value === "string")
        .slice(0, 6)
        .map((n) => ({
          label: String(n.label).slice(0, 24),
          value: String(n.value).slice(0, 120),
          changeable: variant === "sick" || variant === "diary" ? n.changeable !== false : false,
        }))
    : [];
  // Closed-vocabulary enforcement: any symptom label outside the list (or an
  // empty noted on a sick classification) fails the gate → retry/fallback.
  if (variant === "sick") {
    const feeling = noted.find((n) => n.label === "Feeling");
    if (!feeling) return null;
    const labels = feeling.value.split(",").map((s) => s.trim()).filter(Boolean);
    if (labels.length === 0 || labels.some((l) => !known.has(l))) return null;
  }
  return Overlay.parse({
    kind: "voiceResult",
    variant,
    said: transcript, // VERBATIM by construction — the LLM never touches it
    noted,
    workflow,
  });
}

async function classify(transcript: string, retry: boolean): Promise<unknown> {
  const res = await fetch(`${BASE_URL}/chat/completions`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${API_KEY}`,
      "http-referer": "http://localhost:8200",
      "x-title": "Agentic Kinetic router",
    },
    body: JSON.stringify({
      model: MODEL_ID,
      temperature: 0,
      max_tokens: 400,
      messages: [
        { role: "system", content: retry ? `${SYSTEM_PROMPT}\n\nREMINDER: reply with ONLY the JSON object.` : SYSTEM_PROMPT },
        { role: "user", content: transcript },
      ],
    }),
    signal: AbortSignal.timeout(30000),
  });
  if (!res.ok) {
    throw new Error(`model ${res.status}: ${(await res.text()).slice(0, 200)}`);
  }
  const body = (await res.json()) as { choices?: { message?: { content?: string } }[] };
  const content = body.choices?.[0]?.message?.content ?? "";
  const jsonSlice = content.slice(content.indexOf("{"), content.lastIndexOf("}") + 1);
  return JSON.parse(jsonSlice);
}

function streamOverlay(overlay: Overlay): BaseEvent[] {
  const toolCallId = randomUUID();
  const args = JSON.stringify({ overlay });
  return [
    { type: EventType.TOOL_CALL_START, toolCallId, toolCallName: "compose_overlay" },
    { type: EventType.TOOL_CALL_ARGS, toolCallId, delta: args },
    { type: EventType.TOOL_CALL_END, toolCallId },
  ];
}

export const routerAgent = new BuiltInAgent({
  type: "custom",
  factory: async function* (ctx): AsyncGenerator<BaseEvent> {
    const started = Date.now();
    const transcript = extractLastUserTranscript(ctx.input);

    if (!MODEL_ID || !API_KEY) {
      console.error("[router] MODEL_ID/OPENROUTER_API_KEY missing — cannot classify");
      yield* streamOverlay({
        kind: "voiceResult",
        variant: "command_unmatched",
        said: transcript,
        noted: [],
        workflow: null,
      });
      return;
    }

    if (!transcript) {
      console.warn("[router] no user transcript in run input");
      return;
    }

    let overlay: Overlay | null = null;
    for (let attempt = 0; attempt < 2 && !overlay; attempt++) {
      try {
        const raw = await classify(transcript, attempt > 0);
        overlay = sanitizeDecision(raw, transcript);
        if (!overlay) console.warn(`[router] attempt ${attempt + 1}: invalid classification`);
      } catch (err) {
        console.warn(`[router] attempt ${attempt + 1} failed:`, err instanceof Error ? err.message : err);
      }
    }

    // Conservative fallback (workflow-11 §6): an honest "no workflow" result —
    // the patient can send it to the care team; nothing clinical is implied.
    if (!overlay) {
      overlay = { kind: "voiceResult", variant: "command_unmatched", said: transcript, noted: [], workflow: null };
    }

    console.log(
      `[router] ${overlay.kind === "voiceResult" ? `${overlay.variant}${overlay.workflow ? ` → ${overlay.workflow}` : ""}` : overlay.kind} · ${Date.now() - started}ms · "${transcript.slice(0, 60)}"`,
    );
    yield* streamOverlay(overlay);
  },
} as ConstructorParameters<typeof BuiltInAgent>[0]);

export { MAX_STEPS as ROUTER_MAX_STEPS };
