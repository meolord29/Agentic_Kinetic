# Agentic Kinetic — Phone App · Software Architecture Design

> Source of truth: `prototype/phone-app-prototype-v2.html` (v2 agentic-home prototype), the 13 workflow specs in
> `plan-phone-app/agentic workflows/`, and the healthcare stance docs `plan-functionality/patient-app-monitoring-25.md`
> and `plan-functionality/clinic-board-monitoring-25.md`.
>
> **Target stack:** React Native (Android `.apk`) · CopilotKit React Native (`@copilotkit/react-native/headless` ≥ 1.64.0)
> · CopilotKit Runtime v2 agents in TypeScript · **Auth0** user authentication + delegated authorization
> (Auth0 for AI Agents) · **Postgres 16 in Docker** reached with the agent service's *own* least-privilege role.
> **Local-first:** the whole backend is one `docker compose up` on a laptop; the phone and laptop share a hotspot.
>
> **Governing requirement:** the UI is *agentic UI* — every screen the user sees is **described by a UI Agent**
> as data (a plan), rendered by a fixed component registry, and acted on through a closed action vocabulary.
> The agent owns *what* is on screen; deterministic code owns *how* it renders and *what* it can do.

---

## 1. Purpose and governing principles

Agentic Kinetic is a patient companion for kidney-transplant tacrolimus monitoring between monthly blood draws.
The patient app is a **projection**: it displays her own data and her clinician's own words, and interprets nothing.

| # | Principle | Consequence in this architecture |
|---|---|---|
| P1 | **Widgets, not a chat** (monitoring-25 #19) | The chat surface is invisible. The agent communicates exclusively by emitting `HomePlan` objects rendered as a bento grid. No message list ships to the user. |
| P2 | **UI described by the UI Agent** | Every tile (content, size `cols×rows`, tone, order, actions) arrives from the server-side `ui_agent` as validated JSON. The client never decides what is due. |
| P3 | **Deterministic data, generative layout** | State mutations (check-ins, badge thresholds, chains) happen in the Data API with plain code (`logDose()` equivalent). The LLM only *composes* UI from that state. |
| P4 | **Clinical boundary is structural** (monitoring-25 #2, #3) | No health answer path exists. Health questions become `handoff` rows; the vocabulary of tiles/chips is closed enums. An LLM cannot author a question, a task, or an answer. |
| P5 | **Every answer counts the same** (monitoring-25 #17) | Chip sizes, thanks copy and `+1` rules are fixed constants in the contract; reward logic is server-side and cannot be steered by prompt. |
| P6 | **Verbatim relay** (workflows 03/07/12) | Clinician questions, user quotes and diary entries are stored and rendered verbatim; the agent may add nothing around them except fixed copy. |
| P7 | **Audit everything, minimum necessary** (monitoring-25 #24, #25) | Every read/write at the Data API logs actor, purpose and fields returned. Consent scopes are tested at the moment of use. |
| P8 | **AI disclosure** (monitoring-25 #5) | "This app uses AI" ships in the menu; the agent never poses as a clinician; care-team content is labelled as theirs. |
| P9 | **Local-first, demo-portable** | The entire backend is a laptop + `docker compose up`; the only cloud dependency is Auth0. The demo works on a hotspot with no other infrastructure. The server being unreachable must never block a check-in (offline queue). |

---

## 2. System topology

```text
                  ┌─────────────────────────────────────────┐
                  │     Auth0 tenant (cloud)                │
                  │   Universal Login · API · JWKS · PKCE   │
                  └────────────────────┬────────────────────┘
                                       │ PKCE · kinetic:// redirect scheme
                                       ▼

 ┌────────────────────────────────────────────────────────────────────────┐
 │ ANDROID DEVICE (.apk) — on the shared hotspot                          │
 │ ┌─────────────────────────────────────────────────────────────────┐    │
 │ │ React Native app (Expo prebuild)                                │    │
 │ │ · agentic bento home (plan → registry)                          │    │
 │ │ · offline queue (§5.6)                                          │    │
 │ └─────────────────────────────────────────────────────────────────┘    │
 │ ┌───────────────────────┐    ┌──────────────────────────┐              │
 │ │ notifee               │    │ STT (bring-your-own)     │              │
 │ │ local notifications   │    │                          │              │
 │ └───────────────────────┘    └──────────────────────────┘              │
 │                                                                        │
 └──────┬───────────────────────────────────────────┬─────────────────────┘
        │ HTTP :8200                                │ HTTP :8080
        │ SSE · Bearer user token                   │ REST · Bearer user token
        ▼                                           ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │ LAPTOP — docker compose (same hotspot)                                 │
 │ ┌─────────────────────────────────────────────────────────────────┐    │
 │ │ runtime :8200                                                   │    │
 │ │ CopilotKit Runtime v2 · /api/copilotkit (SSE)                   │    │
 │ │ ├─ ui_agent  (UI planner)                                       │    │
 │ │ └─ router    (voice/typed intents)                              │    │
 │ │ JWKS verify ◄── Auth0 (cloud)                                   │    │
 │ │ model calls ──► OpenRouter / model provider (BYOK)              │    │
 │ └────────────────────────────────┬────────────────────────────────┘    │
 │                                  │ tool calls                          │
 │                                  │ delegated user access token         │
 │                                  ▼                                     │
 │ ┌────────────────────────────────┬────────────────────────────────┐    │
 │ │ data-api :8080 · Fastify                                        │    │
 │ │ REST · node-cron sweep · audit · JWKS verify ◄── Auth0 (cloud)  │    │
 │ └─────────────────────────────────────────────────────────────────┘    │
 │                                  │ kinetic_agent role                  │
 │                                  ▼ least privilege · no DDL            │
 │ ┌─────────────────────────────────────────────────────────────────┐    │
 │ │ Postgres 16 (db) — INTERNAL ONLY                                │    │
 │ │ volume · init.sql · no ports published                          │    │
 │ └─────────────────────────────────────────────────────────────────┘    │
 └────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Stack decisions (settled)

| Concern | Decision | Rationale |
|---|---|---|
| Mobile shell | Expo SDK + prebuild, Android target, `.apk` via `eas build -p android --profile preview` or local Gradle | Config plugins manage dev cleartext/permissions safely; headless CopilotKit needs no native peers; bare-RN escape hatch stays open |
| CopilotKit client | `@copilotkit/react-native/headless` **≥ 1.64.0** only | Provider + hooks with zero native peer deps (no `expo-document-picker` / `@gorhom/bottom-sheet` pull-in) |
| Agent framework | TypeScript + CopilotKit Runtime v2 (`CopilotRuntime` + agents + `defineTool`) — **user decision** | One language, one deployable; Auth0 AI JS SDK support |
| Database | **Postgres 16 in Docker** (`db` compose service) — **user decision** | Workflow data is strongly relational and enum-typed (check-in answers, temperature buckets, question approval states); needs transactions for the `logDose → checkins+1 → badge threshold` invariant; local = zero cloud ops for the demo |
| Service hosting | **Full docker-compose**: `db` + `data-api` + `runtime` — **user decision** | One command up; bind-mounted source + `tsx watch` keeps the dev loop fast; reproducible on any laptop |
| Connectivity | Laptop and phone on the **same hotspot**; app → laptop LAN IP over HTTP | No USB tethering or cloud required in the demo path; `adb reverse` and emulator aliases stay as fallbacks (§9.4) |
| Identity | Auth0 (Universal Login, first-party API audience, JWKS) — **user decision** | Auth0 for AI Agents: user auth + delegated authorization to first-party APIs; works from any network because redirects use the `kinetic://` app scheme |
| Push/nudges | **Local notifications** (notifee) scheduled on-device from synced reminders; FCM payload shapes documented as future swap-in | Zero Firebase setup; works fully on the hotspot (§8) |
| i18n | `en` + `zh-Hant` strings from the contract (monitoring-25 #22) | Care plan carries both languages; copy constants are keyed, not hardcoded |

---

## 3. Identity and security architecture

Three distinct identities, three distinct jobs. The requirement — *"an AI agent that has its own authentication
to a database"* — is identity **C**: the Data API owns a dedicated, least-privilege Postgres role that no other
component (and no user) ever uses.

```text
 Elena (RN app)               Auth0 (cloud)                 runtime :8200                data-api :8080         Postgres (db)
 ══════════════               ═════════════                 ═════════════                ══════════════         ═════════════

──────────────────────────────────────────────── A · USER AUTHENTICATION — once per session ────────────────────────────────────────────────
        ├─Universal Login (PKCE)───►│                             │                             │                     │
        │ kinetic:// redirect       │                             │                             │                     │
        │◄─ID token + access token──┤                             │                             │                     │
        │ aud=kinetic-data-api      │                             │                             │                     │
        │ refresh → Keystore        │                             │                             │                     │

─────────────────────────────────────────────────────── B · UI CHANNEL AUTHORISATION ───────────────────────────────────────────────────────
        ├─SSE /api/copilotkit · Bearer <user access token>───────►│                             │                     │
        │                           │◄─JWKS verify (sig·aud·exp)──┤                             │                     │

───────────────────────────── C1 · DELEGATED AUTHORISATION — the agent acts for the user (Auth0 for AI Agents) ─────────────────────────────
        │                           │                             ├─tool call (user token)─────►│                     │
        │                           │                             │ get_due_items · create_handoff …                  │
        │                           │◄─JWKS verify → sub=Elena · scopes=consent─────────────────┤                     │
        │                           │                             │                             │ field projection + audit row

───────────────────────────────────────────────── C2 · THE SERVICE'S OWN DATABASE IDENTITY ─────────────────────────────────────────────────
        │                           │                             │                             ├─connect as─────────►│
        │                           │                             │                             │ kinetic_agent role  │
        │                           │                             │                             │ (pw from .env · scoped grants)
```

### 3.1 Identity A — the user (Auth0 Universal Login)

- `react-native-auth0`, PKCE, refresh-token rotation; tokens live in Android Keystore via the SDK's secure storage.
- Auth0 **API** `kinetic-data-api` registered with scopes mirroring consent: `care:read`, `care:write`,
  `research_deid:read` (granted only when `consent.deidentifiedResearch = on`).
- Redirects use the custom app scheme (`kinetic://login-callback`) — works identically on the hotspot, USB, or a
  future hosted deployment; the Auth0 tenant's **Allowed Callback URLs** list the scheme, not a server address.
- Access-token lifetime short (tighten to 1 h); rotation handled by the SDK; the CopilotKit header set is
  refreshed through React state (see §5.1).
- Re-entry path matches prototype `scr-access`: Face ID / biometric prompt (BiometricPrompt) unlocks the
  locally cached session — never a re-login loop.

### 3.2 Identity B/C1 — delegated authorization (agent acts for the user)

Per Auth0 for AI Agents *call-first-party-apis-on-user's-behalf*:

1. The agent's server tools (`get_patient_state`, `get_due_items`, `create_handoff`, `share_diary_entry`, …) run
   inside the Runtime container.
2. Each tool call forwards **the user's own access token** to the Data API — the agent never holds long-lived
   user credentials and never has "broad, unrestricted access".
3. The Data API validates the JWT (Auth0 JWKS, `aud`, `exp`), resolves `sub → user_id`, enforces scope
   (consent-tested at the moment of use), projects only the fields the endpoint declares, and writes an audit row.
4. Request-scoped token propagation inside the Runtime uses `AsyncLocalStorage` middleware that captures the
   `Authorization` header per SSE request; `defineTool` handlers read the current user's token from that context.

> This is what makes P4 structural: the agent literally cannot read data the user token doesn't open, and the
> API refuses any field not declared by the endpoint (monitoring-25 #25).

### 3.3 Identity C2 — the service's own database authentication (local)

The `data-api` container owns the database identity. Nobody else has one:

- **Role** `kinetic_agent` — created by `deploy/db/init/01-roles.sql`: `LOGIN`, `NOSUPERUSER`, `NOCREATEDB`,
  `NOCREATEROLE`; grants are exactly `SELECT, INSERT, UPDATE, DELETE` on the app schema's tables. No DDL, no
  cross-schema access, no `DELETE` on `audit_log` (append-only at the role level).
- **Migrations** run under a separate admin role (`migrator`, the compose `POSTGRES_USER`) as a one-off
  `migrations` compose job — the app role can never alter schema.
- **Credentials** generated once into `deploy/.env` (`DB_PASSWORD`, `MIGRATOR_PASSWORD`), injected as
  `DATABASE_URL` into the containers. `.env` is gitignored; `.env.example` documents the shape. Rotation =
  edit `.env` + `docker compose up -d db data-api`.
- **The `runtime` container has no `DATABASE_URL`** — its only data path is `http://data-api:8080` on the
  internal compose network. A compromised runtime or leaked model key reaches zero tables.
- **`db` publishes no ports** — SQL is unreachable from the hotspot, the phone, or the laptop's localhost;
  only the compose network can connect.
- **Cloud escape hatch:** this role-based design ports unchanged to hosted Postgres (Cloud SQL IAM database
  authentication swaps the credential mechanism; roles/grants carry over). See §9.5.

| Identity | Holder | Authenticates to | Credential | Lifetime |
|---|---|---|---|---|
| A · Elena | RN app | Auth0, data-api, runtime | OIDC access token (PKCE) | hours |
| B · session | runtime → data-api | Data API | Elena's access token (delegated) | same as A |
| C · service | `data-api` container | Postgres (`kinetic_agent`) | role password from `.env`, scoped grants | static, revocable by role drop |

### 3.4 Consent and audit

- `consents` is an append-only audit table (monitoring-25 #24: revocation recorded, exclusions carried never
  dropped). Scope checks read the latest row at request time.
- `audit_log` rows: `(actor_type user|agent|clinician|system, actor_id, user_id, action, fields[], purpose, at)`.
  The Data API middleware writes one row per request from the decoded JWT + endpoint field manifest.
- The de-identified research path reads through a separate projection endpoint that strips identifiers
  before rows leave Postgres; the training path never sees identifiable data.
- Transport on the hotspot is plain HTTP by design (dev/demo); the JWKS-verified token, scoped role and audit
  trail are the controls that matter. §9.5 notes TLS termination for any future hosted run.

---

## 4. The UI Agent (the critical piece)

### 4.1 Responsibilities and boundaries

| The `ui_agent` … | The `ui_agent` never … |
|---|---|
| receives a state summary (context) and returns **what the home screen should look like** | mutates care data directly (mutations are typed client actions → Data API) |
| sizes every tile (`cols`, `rows`), tints it (`tone`), orders the stack, picks copy from fixed constants | authors questions, answers, tasks, reminders or badge rules (closed enums + server-side rules only) |
| drives overlays (first-time tour steps, voice-popover result states) | answers health questions (router turns those into handoffs, workflow-07) |
| explains nothing in free prose to the user — the chat surface does not exist in the product | sees data the delegated token doesn't open (Auth0 scope enforcement, §3.2) |

Its system prompt is a *renderer of the plan docs*: the sizing grid, tone table, stack rules, priority ladder,
reward rules, copy rules and anti-patterns from `gamification-guidelines.md` are embedded verbatim as
instructions, and **mirrored as executable validators** (§4.6) so a prompt miss cannot ship a violation.

### 4.2 The UI Description Contract (`packages/ui-schema`)

One zod schema is the single contract shared by the server (tool emission + validation) and the client
(frontend-tool parameters + double-check). Zod ≥ 3.24 satisfies CopilotKit's Standard Schema requirement.

```ts
import { z } from "zod";

export const Tone   = z.enum(["hot", "high", "info", "game", "good", "calm", "done"]);
export const Layout = z.object({
  cols: z.union([z.literal(1), z.literal(2)]),
  rows: z.number().int().min(1).max(5),
});

// §4.5 — the closed action vocabulary (the data-* bus from the prototype)
export const Action = z.discriminatedUnion("type", [
  z.object({ type: z.literal("go"), target: z.enum(["now", "milestone", "settings"]) }),
  z.object({ type: z.literal("answer_dose"),        value: z.enum(["taken", "late", "missed", "not_sure"]) }),
  z.object({ type: z.literal("answer_temperature"), value: z.enum(["v36_5", "v37_0", "v37_5", "v38_plus", "not_measured"]) }),
  z.object({ type: z.literal("answer_question"),    value: z.enum(["yes", "no", "not_sure"]) }),
  z.object({ type: z.literal("answer_med_start"),   value: z.enum(["yes", "no", "not_sure"]) }),
  z.object({ type: z.literal("answer_med_timing"),  value: z.enum(["same_time", "different_time", "not_sure"]) }),
  z.object({ type: z.literal("answer_vomit"),       value: z.enum(["within_hour", "later", "didnt_take"]) }),
  z.object({ type: z.literal("ack_reminder"), id: z.string() }),
  z.object({ type: z.literal("confirm_voice_note") }),
  z.object({ type: z.literal("dismiss_celebration") }),
  z.object({ type: z.literal("tour"), dir: z.enum(["next", "back", "skip", "start_checkin"]) }),
  z.object({ type: z.literal("call_care_team") }),
  z.object({ type: z.literal("toast"), message: z.string().max(120) }),
]);

export const Chip = z.object({ label: z.string().max(24), action: Action });

// layout constants encode the prototype's exact silhouettes
export const LAYOUT_2x5   = { cols: 2, rows: 5 };  // celebrations only
export const LAYOUT_2x3   = { cols: 2, rows: 3 };  // main hot cards
export const LAYOUT_2x2   = { cols: 2, rows: 2 };  // questions / thanks / all-clear
export const LAYOUT_1x4   = { cols: 1, rows: 4 };  // temperature — half-width, tall
export const LAYOUT_1x2   = { cols: 1, rows: 2 };  // squares
export const LAYOUT_STRIP = { cols: 2, rows: 1 };  // 1-row strips

// per-component prop schemas discriminate on `component`
export const Tile = z.discriminatedUnion("component", [
  z.object({ component: z.literal("DosePromptCard"),     id: z.string(), layout: z.literal(LAYOUT_2x3), tone: z.literal("hot"),
             props: z.object({ headline: z.string(), reassurance: z.literal("Every answer counts the same.") }),
             chips: z.array(Chip).length(4) }),
  z.object({ component: z.literal("TemperatureCard"),    id: z.string(), layout: z.literal(LAYOUT_1x4), tone: z.literal("hot"),
             props: z.object({ reason: z.enum(["scheduled", "sick_day"]) }),
             chips: z.array(Chip).length(5) }),
  z.object({ component: z.literal("TeamQuestionCard"),   id: z.string(), layout: z.literal(LAYOUT_2x2), tone: z.literal("hot"),
             props: z.object({ text: z.string() }),  // VERBATIM care-team text — validator compares to DB row
             chips: z.array(Chip).length(3) }),
  z.object({ component: z.literal("SamplePrepCard"),     id: z.string(), layout: z.literal(LAYOUT_2x3), tone: z.literal("hot"),
             props: z.object({ when: z.string(), stops: z.array(z.string()).length(4), notes: z.string() }) }),
  z.object({ component: z.literal("VomitCheckCard"),     id: z.string(), layout: z.literal(LAYOUT_2x3), tone: z.literal("hot"), chips: z.array(Chip).length(3) }),
  z.object({ component: z.literal("NewMedCard"),         id: z.string(), layout: Layout, tone: z.literal("hot"),
             props: z.object({ step: z.union([z.literal(1), z.literal(2)]) }) }),
  z.object({ component: z.literal("HandoffCard"),        id: z.string(), layout: z.literal(LAYOUT_2x3), tone: z.literal("high"),
             props: z.object({ q: z.string(), receipt: z.string() }) }),          // q VERBATIM
  z.object({ component: z.literal("DiarySharedCard"),    id: z.string(), layout: z.literal(LAYOUT_2x3), tone: z.literal("high"),
             props: z.object({ text: z.string(), receipt: z.string() }) }),       // text VERBATIM
  z.object({ component: z.literal("BadgeCelebrationCard"), id: z.string(), layout: z.literal(LAYOUT_2x5), tone: z.literal("hot"),
             props: z.object({ n: z.number(), label: z.string(), copy: z.string(), shelf: z.array(z.object({ n: z.number(), earned: z.boolean() })) }) }),
  z.object({ component: z.literal("ThanksCard"),         id: z.string(), layout: z.literal(LAYOUT_2x2), tone: z.literal("good"),
             props: z.object({ plus: z.boolean(), progressText: z.string() }) }),
  z.object({ component: z.literal("AllClearCard"),       id: z.string(), layout: z.literal(LAYOUT_2x2), tone: z.literal("calm") }),
  z.object({ component: z.literal("DoneRow"),            id: z.string(), layout: z.literal(LAYOUT_STRIP), tone: z.literal("done"),
             props: z.object({ label: z.string(), status: z.string() }) }),
  z.object({ component: z.literal("BookedRow"),          id: z.string(), layout: z.literal(LAYOUT_STRIP), tone: z.literal("high"),
             props: z.object({ label: z.literal("Booked by your care team"), when: z.string(), test: z.string() }) }),
  z.object({ component: z.literal("ReminderStrip"),      id: z.string(), layout: z.literal(LAYOUT_STRIP), tone: z.literal("info"),
             props: z.object({ text: z.string() }) }),
  z.object({ component: z.literal("BadgesSquare"),       id: z.string(), layout: z.literal(LAYOUT_1x2), tone: z.literal("game"),
             props: z.object({ progressText: z.string() }) }),
  z.object({ component: z.literal("CareTeamSquare"),     id: z.string(), layout: z.literal(LAYOUT_1x2), tone: z.literal("calm") }),
]);

export const Overlay = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("tour"), step: z.number().int().min(0).max(4),
             target: z.enum(["agent-stack", "hot-tile", "fab", "level-ring", "menu"]),
             headline: z.string(), purpose: z.string(), last: z.boolean() }),
  z.object({ kind: z.literal("voiceResult"), variant: z.enum(["dose", "health", "sick", "diary", "command_matched", "command_unmatched"]),
             said: z.string(),                                   // VERBATIM transcript
             noted: z.array(z.object({ label: z.string(), value: z.string(), changeable: z.boolean() })).default([]),
             workflow: z.string().nullable().default(null) }),
]);

export const HomePlan = z.object({
  planId: z.string(),
  header: z.object({
    greeting: z.string(),          // "Hi, Elena" / "Good evening, Elena"
    dateLabel: z.string(),
    level: z.number().int().min(1),
    levelPct: z.number().min(0).max(100),
  }),
  tiles: z.array(Tile).max(14),
  overlays: z.array(Overlay).max(1).default([]),
});
```

### 4.3 Delivery mechanism — why a frontend tool, not shared state

React Native reality check (from the CopilotKit RN docs):

- The **shared-state CoAgents API (`useCoAgent`) is not exported on React Native** — the shared hooks are
  `useAgent`, `useFrontendTool`, `useHumanInTheLoop`, `useAgentContext`, `useRenderTool`, `useRenderToolCall`, …
- Therefore the plan travels **down** as a frontend tool call, and state travels **up** as agent context:

| Direction | Mechanism | Payload |
|---|---|---|
| ↓ UI | `useFrontendTool({ name: "compose_home" })` | `HomePlan` (the contract above) |
| ↓ overlays | `useFrontendTool({ name: "compose_overlay" })` | `Overlay` |
| ↑ context | `useAgentContext` | `PatientContextSummary` (§6.2) |
| ↑ intent | `agent.addMessage(transcript)` + `copilotkit.runAgent({ agent: "router" })` | verbatim transcript |
| ↑ action | deterministic dispatch → Data API REST | typed action enums |

The existing workflow docs' "CopilotKit mapping" sections use web-era names; the conversion is mechanical:

| Workflow doc says | Ships as |
|---|---|
| `useCoAgent` shared state | `useAgentContext` (up) + `compose_home` (down) |
| `useCopilotAction` (client render/effect) | `useFrontendTool` |
| `useCopilotAction` (agent-side logic) | server `defineTool` |
| `render_*` actions | registry components + plan tiles |

### 4.4 Client-side wiring of the plan channel

```tsx
// apps/mobile/src/agent/useComposeHome.ts
import { useFrontendTool } from "@copilotkit/react-native/headless";
import { HomePlan, validatePlan } from "@kinetic/ui-schema";
import { usePlanStore } from "../plan/store";

export function useComposeHome() {
  const commit = usePlanStore((s) => s.commit);
  useFrontendTool({
    name: "compose_home",
    agentId: "ui_agent",
    description:
      "Replace the current home plan: header, bento tiles (sized + toned), and at most one overlay. " +
      "Tiles must reference state the patient context actually carries.",
    parameters: HomePlan,
    handler: async (plan) => {
      commit(validatePlan(plan));   // zod + §4.6 invariants; invalid → all-clear fallback
      return "rendered";
    },
  });
}
```

The tool declares **no `render`** — nothing is drawn inside a chat. The Home screen subscribes to the plan
store and lays tiles into the bento grid with the prototype's 45 ms stagger and reduced-motion collapse.
(If a tile renderer were ever passed to `useFrontendTool`, it must be annotated
`FrontendToolRenderFunction<T>` — bare strings typecheck then throw inside `FlatList`.)

### 4.5 Component Registry — the closed renderer set

Exactly 17 tile components + 2 overlay hosts + header chrome. **New chrome is forbidden** (gamification §7);
this table is the whole rendering vocabulary, lifted from `AK.reg(...)` weights in the prototype:

| Component | Group | Weight | Layout | Tone | Chip count |
|---|---|---|---|---|---|
| `BadgeCelebrationCard` | main | 99 | `2×5` | hot | Keep going |
| `ThanksCard` | main | 90 | `2×2` | good | — (+1 pill only when `plus`) |
| `DosePromptCard` | main | 80 | `2×3` | hot | 4 (2-col grid) |
| `SamplePrepCard` | main | 78 | `2×3` | hot | — (4-stop timeline) |
| `VomitCheckCard` | main | 76 | `2×3` | hot | 3 (2-col grid) |
| `TemperatureCard` | main | 75 | `1×4` (half-width, tall — exact silhouette kept) | hot | 5 (single column) |
| `TeamQuestionCard` | main | 74 | `2×2` | hot | 3 (one row) |
| `NewMedCard` | main | 72 | `2×2` (step 1) / `2×3` (step 2) | hot | 3 / 3 |
| `HandoffCard` | main | 70 | `2×3` | high | quote + team line + call + receipt |
| `DiarySharedCard` | main | 69 | `2×3` | high | quote + receipt |
| `AllClearCard` | main | −1 fallback | `2×2` | calm | — |
| `DoneRow` | done | 50 dose · 48 temp · 47 feelings · 46 question · 45 vomit · 44 med-watch · 43 diary | strip | done | — |
| `BookedRow` | sub | 50 | `2×1` | high | — |
| `BadgesSquare` | sub | 40 | `1×2` | game | — |
| `CareTeamSquare` | sub | 39 | `1×2` | calm | — |
| `ReminderStrip` | sub | 30 | `2×1` | info | — |
| `MilestoneHero` (+ `BadgeShelf`) | milestone screen | — | hero card `.now` | hot/calm | — |

Non-tile surfaces: `Header` (mark, greeting, `LevelRing` conic, menu), `FabWrap` (66 px hold-to-talk),
`VoicePop` (listening / result states), `TourLayer` (spotlight + coach mark), `Toast`, menu sheet,
`ScenarioDrawer` + `KnowledgeInspector` (dev only, §5.5).

Registry entries are typed as `Record<ComponentName, React.ComponentType<TileProps>>` — a plan referencing an
unknown component fails validation *before* render, so the LLM can never conjure new UI.

### 4.6 Deterministic plan invariants (the guardrail validators)

`validatePlan(plan, snapshot)` runs in both `ui_agent` (emit-time) and the client (commit-time). Any failure →
log + **all-clear fallback plan** (never a broken screen, never a partial stack):

1. **Order** — done rows first → main tiles by weight desc → sub tiles; weights are constants, not LLM output.
2. **One question at a time** — at most one tile with `chips` may have tone `hot`; celebrations (`2×5`) suppress
   `ThanksCard` until `dismiss_celebration`.
3. **No invented tasks** — every `TeamQuestionCard.text` must byte-match an approved DB question; every
   `BookedRow.when` must match an accepted booking; a tile type is *admissible* only if the snapshot carries the
   corresponding fact (e.g. `TemperatureCard` requires `temp.due`).
4. **Reward invariants** — `ThanksCard.plus=true` only within 1 plan of a dose answer; badges only at exact
   thresholds {1, 7, 30, 100, 365} (server-computed); sick-day/diary plans may not contain `BadgeCelebrationCard`.
5. **Verbatim fields** — handoff/diary/question strings compared to their DB rows; diffs rejected.
6. **Copy constants** — reassurance line, thanks copy, progress-text format are emitted from the shared
   constants file; the LLM picks them, never writes them.

### 4.7 The plan loop

```text
 Elena             RN app                data-api :8080         ui_agent (runtime :8200)
 ═════             ══════                ══════════════         ════════════════════════

   │                  ├─GET /me/snapshot───────►│                           │
   │                  │ (Bearer user token)     │                           │
   │                  │◄─context + snapshot─────┤                           │
   │                  ├─useAgentContext(...) → runAgent────────────────────►│

   │                  │                         │◄─get_due_items────────────┤
   │                  │                         │ (delegated user token)    │
   │                  │                         ├─due facts────────────────►│
   │                  │                         │ dose due? question waiting? booking tomorrow?

   │                  │◄═compose_home(HomePlan)═════════════════════════════┤
   │                  │ validatePlan → store.commit → bento renders (45 ms stagger)

   ├─taps chip───────►│                         │                           │
   │ "Took it late"   │                         │                           │
   │                  ├─POST /me/checkins──────►│                           │
   │                  │ { answer:"late" } · deterministic                   │
   │                  │                         │ logDose tx: done · checkins+1 · badge check
   │                  │◄─snapshot + sideEffects─┤                           │
   │                  │ { badgeUnlocked? }      │                           │

   │                  ├─context refreshed → re-plan────────────────────────►│

   │                  │◄═compose_home(...)══════════════════════════════════┤
   │                  │ celebration 99 or ThanksCard 90 → next hot tile     │
```

The split is the architecture's spine: **mutations are code, composition is the agent, rendering is the
registry.** The agent is never a state authority — if the Runtime is unreachable, the client renders the last
valid plan plus a quiet "reconnecting" state; check-in chips still work through the offline queue (§5.6).

### 4.8 Overlays

- **First-time tour (workflow-10)** — the plan's `overlays[0] = { kind:"tour", … }` mounts `TourLayer` over the
  *real* planned home (spotlight mode, not focus mode). Targets are registry-anchored refs
  (`agent-stack`, `hot-tile`, `fab`, `level-ring`, `menu`); measured with `measureInWindow`, dimmed by an
  absolute overlay + border cutout; `Back/Next/Skip/Start my first check-in` dispatch the `tour` action.
  Dark-tap advance disabled on the last step; replayable on demand ("show me around").
- **Voice result (workflows 01b/07/08/11/12)** — `overlays[0] = { kind:"voiceResult", … }` drives the
  `VoicePop` result state: verbatim "You said", noted rows (label / bold value / **Change**), confirm/re-record.
  Nothing commits before "Looks right".

### 4.9 Failure posture

| Failure | Behaviour |
|---|---|
| `compose_home` fails validation | all-clear fallback plan + `KnowledgeInspector` flags the violation (dev); server logs plan + violation |
| Runtime unreachable (laptop off, hotspot dropped) | last valid plan stays; check-ins queue offline (§5.6); banner retries with backoff |
| Model provider error/timeout | Runtime returns agent error → `onError` → fallback plan; reminders already synced stay scheduled on-device |
| STT absent (de-Googled ROM) | mic FAB hides, typed-input path remains (deterministic guard, per RN docs) |

---

## 5. React Native client architecture

### 5.1 CopilotKit RN constraint ledger (bake into CI, not memory)

| Constraint | Handling |
|---|---|
| `/headless` subpath exists only ≥ 1.64.0 | pin `@copilotkit/react-native@^1.64` in `package.json`; `npm ls` in CI |
| `react-native-get-random-values` must be the **first import**, before any CopilotKit import (first-writer-wins crypto) | `index.js` line 1; ESLint `import/order` rule enforcing it |
| Hermes lacks Web streams/encoding/crypto | `import "@copilotkit/react-native/polyfills"` on line 2 (barrel; provider re-installs idempotently) |
| `jose` (via telemetry dep) breaks release bundles on `node:` imports | Metro `resolveRequest` override forcing `unstable_conditionNames: ["browser"]` **for `jose` only** (never global) |
| Package exports need Metro ≥ 0.82 / RN ≥ 0.79 | pin RN 0.79+ |
| Provider `headers` is resolved **on render**, not per request | token held in React state → rotation re-renders provider; plus `copilotkit.setHeaders()` on refresh for safety |
| Cloud props (`publicApiKey`/`licenseToken`) unsupported | self-hosted `runtimeUrl` only — by design here |
| No Inspector, no `@copilotkit/voice`, no `threadId` on `useAgent` | §5.5 dev harness; §5.4 own STT; thread scoping deferred (backend threads table ready) |
| Register frontend tools **once per agent** | tool registration isolated in `src/agent/tools.ts`, mounted at App root |
| Android blocks cleartext HTTP in release builds | demo `.apk` flavor allows plaintext **scoped to the dev LAN** via network-security-config (§9.4); any future hosted build drops it (TLS) |

### 5.2 Navigation — trail stack, not tabs

Prototype hash routes map 1:1; `data-back`'s trail becomes a small stack with fallbacks:

```
Onboarding stack:  Welcome → Consent → Access → Permissions → (Home)
Main stack:        Home (planner surface) ⇄ Milestone · Settings · Lock overlay
fallbacks:         Home back → Home · Milestone back → Home · Lock → Welcome (fresh session)
```

React Navigation native-stack, 2 navigators, deep links `kinetic://now?focus=<tileId>` for notification taps.

### 5.3 Module layout

```
apps/mobile/
  index.js                     # 1: react-native-get-random-values  2: polyfills  3: everything else
  App.tsx                      # Auth0Provider → CopilotKitProvider(headers=state) → Navigation
  src/
    agent/
      provider.tsx             # runtimeUrl from serverConfig, headers {Authorization}, onError
      tools.ts                 # compose_home · compose_overlay  (registered once, app root)
      usePatientContext.ts     # useAgentContext(summary) — re-registered on snapshot change
      useCareRouter.ts         # transcript → router agent (addMessage + runAgent)
    plan/
      store.ts                 # zustand: { plan, commit(), appliedAt }
      validate.ts              # zod + §4.6 invariants (client-side double-check)
      registry.ts              # name → component map (typed, exhaustive)
    screens/                   # Welcome · Consent · Access · Permissions · Home · Milestone · Settings · Lock
    components/                # the 17 registry components + Header/FabWrap/VoicePop/TourLayer/Toast/Sheet
    voice/
      useHoldToTalk.ts         # record → STT → confirm-before-commit (privacy line always shown)
    data/
      serverConfig.ts          # server address pairing (§9.4): LAN IP store, QR scan, /healthz probe
      api.ts                   # typed REST client (user token, retry, offline queue §5.6)
      snapshot.ts
      reminders.ts             # reminder sync → notifee scheduling (§8)
    nav/trail.ts               # stack + fallbacks + deep links
    dev/
      ScenarioDrawer.tsx       # the 11 scenarios (morning, evening, question, newmed, temp, badge, health, sick, diary, clear, firsttime)
      KnowledgeInspector.tsx   # agent-knowledge panel: context sent · plan received · violations
```

### 5.4 Voice pipeline (bring-your-own STT)

`@copilotkit/voice` is not adapted for React Native, so:

1. Hold FAB (66 px) → `Listening` state: wave bars, **Release to send**, privacy line
   ("Only the words are kept. The voice itself is never analysed."), plus the *typed request* field
   (always-available redundant input, monitoring-25 #23).
2. Release → recording buffer sent to STT (on-device SpeechRecognizer when present; cloud STT via a
   thin proxy on `data-api` otherwise) → **audio buffer discarded immediately**; only the transcript
   persists (it becomes `voice_notes.transcript`).
3. Transcript = message to the `router` agent → deterministic keyword classifier first
   (`parseSymptoms` / `extractDiary` / `COMMAND_RULES` ported verbatim from the prototype), LLM fallback only
   for misses → `compose_overlay(voiceResult)` → **Looks right** commits via typed Data API calls;
   **Say it again** re-records. No commit before confirmation (workflows 07/08/12).
4. A deterministic **Send** control always ends the turn (never silence detection only).

### 5.5 Dev harness (replaces the RN-missing Inspector)

The prototype's demo panel ships as a debug-only drawer:

- **ScenarioDrawer** — seeds the local `data-api` with each of the 11 demo scenarios' state.
- **KnowledgeInspector** — shows exactly what `useAgentContext` registered, the raw `HomePlan` received,
  validation verdicts, and the current mutation log. This implements the CopilotKit docs' "prove it works"
  strategy on-device: context-in vs plan-out vs pixels-on-screen must agree, because *rendering data on screen
  does not give the agent access to it*.

### 5.6 Offline queue (local-server requirement)

The server lives on a laptop that can close, sleep, or leave the hotspot. The client therefore treats the
`data-api` as an eventually-reachable authority:

- **Check-ins and confirmations** (dose, temperature, symptoms, med-watch, question answers, diary, handoffs)
  enqueue locally (MMKV/SQLite) with a client `eventId` (UUID) the moment the user commits them — the UI
  advances immediately on optimistic state (the prototype's instant re-plan).
- A flush loop retries with backoff; the server deduplicates on `eventId` (unique index) so retries are safe.
- Optimistic entries are visually indistinguishable, but `KnowledgeInspector` (dev) marks "queued · not yet
  acked". Badge thresholds and chains are **recomputed server-side at flush time** from the event's timestamp,
  so the reward invariants (§4.6-4) hold even for late-synced answers.
- The plan store keeps the **last valid plan**; a quiet "reconnecting" chip appears on Home. No tile ever
  prompts the user to "try again" — the queue is the app's job, not hers.

---

## 6. Agent layer (`runtime` container)

### 6.1 Service sketch

```ts
// services/runtime/src/server.ts
import { createServer } from "node:http";
import { CopilotRuntime } from "@copilotkit/runtime/v2";
import { createCopilotNodeListener } from "@copilotkit/runtime/v2/node";
import { uiAgent, routerAgent } from "./agents";
import { userContext } from "./middleware/userContext"; // captures Bearer token into ALS

const runtime = new CopilotRuntime({
  agents: { ui_agent: uiAgent, router: routerAgent },
});

createServer(
  userContext(
    createCopilotNodeListener({ runtime, basePath: "/api/copilotkit" }),
  ),
).listen(Number(process.env.PORT ?? 8200));
```

- Runs as the `runtime` compose service (bind-mounted source + `tsx watch`); publishes `8200` on the LAN.
- JWKS verification middleware rejects requests without a valid user token (the provider's `headers` carries it).
- `AsyncLocalStorage` exposes `currentUser.token` to every tool handler — request-scoped delegated auth (§3.2).
- All outbound Data-API calls go to `DATA_API_URL` (`http://data-api:8080` on the compose network).
- Model wiring: `BuiltInAgent({ model })` string form honors OpenAI-compatible base-URL overrides → **OpenRouter
  works without code changes**; the key itself is BYOK per request (§9.3) with an optional env fallback.

### 6.2 Agents

| Agent | Model role | Emits | Consumes |
|---|---|---|---|
| `ui_agent` | home/overlay planner — deterministic-first, LLM composes layout + copy selection | `compose_home`, `compose_overlay` | `PatientContextSummary` (context), `get_due_items` (tool) |
| `router` | transcript classifier + confirm-before-act driver | `compose_overlay(voiceResult)`, handoff creation | verbatim transcript, workflow routing table (workflow-11) |

Both are `BuiltInAgent` instances (or thin custom agents) with `maxSteps` bounded (planner ≤ 4, router ≤ 3) so
runs can't linger (RN run-lifecycle guidance: gate overlays on the *falling edge* of `isRunning`).

### 6.3 Server tools (`defineTool`, executed inside the Runtime, calling the Data API)

| Tool | Data API call | Purpose |
|---|---|---|
| `get_due_items` | `GET /me/due` | the only planning input: facts the plan may reference (invariant §4.6-3) |
| `create_handoff` | `POST /me/handoffs` | verbatim question/request → care team (workflows 07/11) |
| `share_diary_entry` | `POST /me/diary` | verbatim entry + confirmed noted themes (workflow-12) |
| `request_new_workflow` | `POST /me/handoffs {kind:"workflow_request"}` | "no workflow for that" escalation (workflow-11) |
| `set_reminder_ack` | `POST /me/reminders/:id/ack` | reminder strip tap |

Check-in answers, temperature, symptoms, med-watch are **not** agent tools — they are client actions straight
to the Data API (deterministic, auditable, offline-queueable).

### 6.4 Planner prompt architecture

The `ui_agent` system prompt is generated from one source file that fuses, in order:

1. Role + output mode ("emit `compose_home`; never narrate; never invent").
2. The sizing grid, tone table, stack rules, priority ladder, reward rules, copy rules and anti-patterns —
   **verbatim from `gamification-guidelines.md`**.
3. The workflow trigger table (weights 99→30, when-conditions) from workflows 01–12.
4. Clinical boundary: questions/instructions/booking text are quoted from context only.
5. Instruction to refuse facts absent from `get_due_items` (counters the silent-context failure the RN docs warn about).

The same rules exist as §4.6 validators. Prompt explains; validators enforce.

---

## 7. Data architecture (Postgres 16, `db` container)

### 7.1 Why relational

The 13 workflows produce exactly the shape Postgres is for: enum-typed answers
(`taken|late|missed|not_sure`, `yes|no|not_sure`, temperature buckets), 1:N relationships
(user → checkins → badge unlocks), transactional invariants (`logDose` = one transaction:
answer + `checkins+1` + threshold eval + flash/unlock side effect), verbatim-text rows with approval states
(clinician-authored questions: `draft → approved → waiting → answered` — a *proposal never renders as booked*,
monitoring-25 #14), and append-only consent/audit trails.

### 7.2 Schema (derived from every workflow's "State mutations" tables)

```sql
users            (id, auth0_sub UNIQUE, display_name, language, timezone, created_at)
consents         (id, user_id, scope own_care|deidentified_research|named_research,
                  state always_on|off|not_offered, actor, changed_at)          -- append-only audit
checkins         (id, user_id, kind dose, answer taken|late|missed|not_sure,
                  dose_at, logged_at, client_event_id UNIQUE,                  -- §5.6 dedup
                  -- sample-validity annotations (monitoring-25 #7)
                  food_within_window bool, minutes_dose_to_meal int,
                  meal_size_vs_usual, typical_day bool,
                  voice_note_id → voice_notes)                                 -- workflow-01
temperature_readings (id, user_id, bucket v36_5|v37_0|v37_5|v38_plus|not_measured,
                  reason scheduled|sick_day, taken_at, client_event_id UNIQUE) -- workflow-05, 08
symptom_events   (id, user_id, labels text[], source sick_note|diary,
                  transcript, confirmed_at, client_event_id UNIQUE)            -- workflow-08, 12
vomit_checks     (id, user_id, answer within_hour|later|didnt_take,
                  asked_at, answered_at, stale_after 24h)                      -- workflow-08
care_questions   (id, user_id, text, author clinician_id, approved_at,
                  status draft|approved|waiting|answered,
                  answer yes|no|not_sure)                                      -- workflow-03 (verbatim; drafts never render)
med_watches      (id, user_id, step 1|2, start_answer, timing_answer,
                  status waiting|done, client_event_id UNIQUE)                 -- workflow-04
bookings         (id, user_id, test_name, for_date, fasting bool,
                  offsets [before_dose,1h,3h,6h], accepted_by, proposal_id)    -- workflow-02; NULL until clinician accepts
reminders        (id, user_id, text, fire_at, delivered_at, acked_at,
                  notif_id TEXT)                                               -- workflow-02; notif_id ↔ notifee id
handoffs         (id, user_id, kind question|workflow_request, q VERBATIM,
                  status sent|answered, created_at, client_event_id UNIQUE)    -- workflow-07, 11
diary_entries    (id, user_id, text VERBATIM,
                  noted_feelings text[], noted_medicine, has_question bool,
                  shared_at, client_event_id UNIQUE)                           -- workflow-12
voice_notes      (id, user_id, transcript, noted jsonb, kind, confirmed_at)   -- transcript only; audio never stored
gamification     (user_id PK, checkins int, UNIQUE-threshold unlocks derived)
badges_earned    (id, user_id, n 1|7|30|100|365, earned_at)
ui_plans         (id, user_id, plan jsonb, trigger, created_at)               -- audit/replay of agent output
threads          (id, user_id, agent_id, created_at)                          -- ready for CopilotKit threads (RN support pending)
audit_log        (id, actor_type user|agent|clinician|system, actor_id,
                  user_id, action, fields text[], purpose, at)
```

### 7.3 Data rules

- **Verbatim relay**: `care_questions.text`, `handoffs.q`, `diary_entries.text`, `voice_notes.transcript` are
  rendered byte-identical; validators diff plan content against these rows.
- **Only `POST /me/checkins` increments `checkins`** (gamification rule 1), inside one transaction with the
  badge-threshold check — recomputed at sync time from the event timestamp, so offline-queued answers land
  on the correct day. Temperature/symptoms/questions/diary/handoffs never increment.
- **Silence is a state**: unanswered due items get `missing_after_hours` timestamps by the scheduler sweep and
  can escalate on the clinician side; the patient surface never re-asks more than once per dose.
- **Minimum necessary**: every endpoint declares its returned fields; the audit middleware records them.
- **Role enforcement** (§3.3): `kinetic_agent` has no DDL and no `DELETE` on `audit_log` — a test in CI asserts
  a DDL/audit-delete attempt fails.

---

## 8. Reminders and nudges (local-first)

```text
    SERVER (laptop · compose)                           DEVICE (Android · same hotspot)
    ═════════════════════════                           ═══════════════════════════
        │ node-cron (every 5 min) · compute-due sweep:        │
        │   · dose window by daypart      · booking tomorrow  │
        │   · reminder fire times         · stale sweep →     │
        │     missing_after_hours (clinician side only)       │
        ├───reminders rows (fire_at · text · kind)───────────►│
        │                                                     │
        │◄══device sync · GET /me/snapshot════════════════════┤
        │   (app open · resume · hourly bg on hotspot)        │
        ╟══reminders with future fire_at═════════════════════╝│
        │                                                     │
                                                    ┌────────────────────────────────────────────────┐
                                                    │ notifee schedules local notifications          │
                                                    │ 1 · action-chip check-in                       │
                                                    │    "Morning dose — How did this morning's"     │
                                                    │     dose go?"  [ Took it ][ Took it late ]     │
                                                    │ 2 · passive FYI                                │
                                                    │    "Samples tomorrow · booked · fasting"       │
                                                    └────────────────────────────────────────────────┘
        │                                             tap → deep link kinetic://now?focus=dose
        │                                             → snapshot refresh → agent re-plan

        │◄──chip log · POST /me/checkins──────────────────────┤
        │   (online now) or offline queue (§5.6)              │
```

- **Two on-device shapes**, mirroring the prototype lock screen:
  1. *Action-chip check-in* — "Morning dose — How did this morning's dose go?" with **Took it / Took it late**
     actions; an action enqueues the check-in immediately (offline queue) and deep-links home.
  2. *Passive FYI* — "Samples tomorrow · Booked by your care team · Fingerstick. Fasting." → deep link.
- **Honest limitation (accepted):** without FCM, a notification only fires if the device has synced the
  upcoming reminder (app opened while on the hotspot, or hourly background sync). The demo path — phone on the
  hotspot with the app backgrounded — works. FCM remains the future swap for anywhere-push: `data-api` already
  computes the payloads; adding a Firebase project later replaces the notifee scheduler, not the API (§9.5).
- **Stale sweep**: `missing_after_hours` marks are clinician-side only; the patient surface never re-asks.

---

## 9. Local-first deployment and networking

### 9.1 Full compose stack

```yaml
# deploy/docker-compose.yml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: kinetic
      POSTGRES_USER: migrator                    # admin role — migrations only
      POSTGRES_PASSWORD: ${MIGRATOR_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./db/init:/docker-entrypoint-initdb.d    # creates kinetic_agent (§3.3) + seed helper
    # no ports — SQL is unreachable from the hotspot/localhost

  migrations:
    build: ../services/data-api
    command: npm run migrate
    environment:
      DATABASE_URL: postgres://migrator:${MIGRATOR_PASSWORD}@db:5432/kinetic
    depends_on: [db]
    restart: "no"

  data-api:
    build: ../services/data-api
    command: npm run dev                          # tsx watch over bind mount
    environment:
      DATABASE_URL: postgres://kinetic_agent:${DB_PASSWORD}@db:5432/kinetic
      AUTH0_ISSUER: https://${AUTH0_TENANT}/
      AUTH0_AUDIENCE: kinetic-data-api
      PORT: 8080
    ports:
      - "8080:8080"                               # published to the LAN (hotspot)
    volumes:
      - ../services/data-api:/app

  runtime:
    build: ../services/runtime
    command: npm run dev
    environment:
      DATA_API_URL: http://data-api:8080          # internal — never exposed
      AUTH0_ISSUER: https://${AUTH0_TENANT}/
      AUTH0_AUDIENCE: kinetic-data-api
      PORT: 8200
    ports:
      - "8200:8200"                               # published to the LAN (hotspot)
    volumes:
      - ../services/runtime:/app

volumes:
  pgdata: {}
```

```bash
-- deploy/db/init/01-roles.sql  (runs once on first volume init, as migrator)
\set pw `echo "$DB_PASSWORD"`
CREATE ROLE kinetic_agent LOGIN PASSWORD :'pw'
  NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT USAGE ON SCHEMA app TO kinetic_agent;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA app TO kinetic_agent;
GRANT DELETE ON app.checkins, app.temperature_readings, app.reminders TO kinetic_agent; -- corrections only
REVOKE ALL ON app.audit_log FROM kinetic_agent;               -- insert-only via dedicated grant
GRANT INSERT ON app.audit_log TO kinetic_agent;               -- audit is append-only at role level
```

- `deploy/.env` (gitignored; `.env.example` committed): `DB_PASSWORD`, `MIGRATOR_PASSWORD`,
  `AUTH0_TENANT`, `LAN_IP` (convenience default for docs/scripts).
- One command: `docker compose --env-file .env up --build`. Rebuild-on-change is avoided by bind mounts +
  `tsx watch`; a fresh laptop clone → demo in ~5 minutes (image pulls dominate).

### 9.2 Environment matrix

| | demo/dev (the product of this doc) | future hosted (§9.5) |
|---|---|---|
| Where | laptop, full compose | Cloud Run ×2 + managed Postgres |
| Device network | shared hotspot → `http://<LAN_IP>` | internet → HTTPS domain |
| Model auth | **BYOK** OpenRouter token from Settings (primary); env key optional | central key in Secret Manager |
| Auth0 | dev tenant, `kinetic://` callbacks | prod tenant, same scheme |
| DB credential | `kinetic_agent` role, `.env` | same role model; IAM DB auth optional upgrade |
| Push | notifee local (synced) | FCM |
| Cleartext | allowed, scoped to LAN (dev flavor) | TLS only |

### 9.3 Model provider — OpenRouter BYOK is the primary posture

The prototype already stores a user-supplied OpenRouter token on-device (`ak.openrouter.token`, Settings
screen) — the local architecture keeps that pattern as the default:

| Option | Mechanism | When | Notes |
|---|---|---|---|
| **(b) BYOK — primary** | Settings-screen token sent per request (`x-model-key` header); runtime builds the model instance per run; base URL `https://openrouter.ai/api/v1` | demo/dev | **keyless backend** — no model secret exists on the laptop at all; each demo attendee brings their own key; matches the prototype screen exactly |
| (a) central env key | `OPENAI_BASE_URL` + `OPENAI_API_KEY` env on the runtime container | CI, scripted tests, users without a key | identical code path, env fallback only |
| (c) both *(implemented)* | header overrides env when present | — | runtime agent factory reads `x-model-key` → per-request model; env otherwise |

**Resolved decision** (was pending in v1): local-first makes BYOK the sensible default; the central-key
discussion moves with the hosted appendix (§9.5).

### 9.4 Device networking (settled — the hotspot topology)

| Path | Runtime URL on device | When |
|---|---|---|
| **Hotspot LAN — primary** | `http://<laptop-LAN-IP>:8200/api/copilotkit` (data-api `:8080`) | the demo path: laptop + phone on the same hotspot |
| USB fallback | `adb reverse tcp:8200 tcp:8200` + `tcp:8080` → `localhost` | no hotspot / firewall-lab environments |
| Emulator | `10.0.2.2` (Android alias for host loopback) | dev without hardware |

- **Server pairing** lives in the app (extends the prototype's Settings screen): a **"Server address"** field
  storing `http://<ip>` (both ports derived), an optional **QR code** on the laptop (`deploy` prints a QR with
  the LAN IP after compose-up) so pairing is one scan, and a **`/healthz` probe** on both services that the
  pairing flow requires to pass before saving.
- **Cleartext HTTP**: the demo `.apk` flavor ships a `network-security-config` allowing plaintext **only for
  the dev LAN** (or, pragmatically for a hackathon build, `usesCleartextTraffic: true` in the demo flavor —
  never in a hosted build). No iOS work exists (Android-only target).
- **IP drift** (hotspot re-assigns addresses): the QR re-scan is one tap; mDNS discovery (`kinetic.local`) is a
  noted future convenience, not a dependency.
- **Verification ladder** (per CopilotKit RN docs, no browser/Inspector exists):
  1. `npx copilotkit verify --round-trip --runtime-url http://<LAN_IP>:8200/api/copilotkit --agent ui_agent`
  2. on-device screencap (`adb exec-out screencap -p`) + `adb logcat -d -s ReactNativeJS:E` clean
  3. grounding check via `KnowledgeInspector`: plan references ⊆ snapshot facts

### 9.5 Future: hosted appendix (out of scope now, mapped for later)

The service boundaries are drawn so hosting is a re-plumb, not a rewrite:

| Local | Hosted swap |
|---|---|
| `runtime` container | Cloud Run `kinetic-runtime` (min-instances 1, SSE supported, timeout ≥ 300 s) |
| `data-api` container | Cloud Run `kinetic-data-api` behind TLS |
| `db` container + volume | Cloud SQL Postgres — same `kinetic_agent` role model; credential becomes IAM DB auth |
| `.env` secrets | Secret Manager |
| node-cron + notifee | Cloud Scheduler + FCM (payload shapes already computed, §8) |
| BYOK OpenRouter | central key in Secret Manager (or keep BYOK) |
| cleartext LAN | TLS termination, ATS/cleartext flags removed from the hosted flavor |

---

## 10. Workflow → implementation map

| Workflow | Trigger (state) | Plans via | Mutations via | Registry components |
|---|---|---|---|---|
| 00 onboarding | `registered=false` / unlock | full-screen stacks (not bento); ui_agent updates CTA state | `POST /me/consent`, `/me/session/biometric` | Welcome, ConsentScopeRow, PinDots, PermissionRow |
| 01 morning dose | `daypart=morning ∧ dose.due` | tile w80 `2×3 hot` | `POST /me/checkins` (only +1 path) | DosePromptCard, ThanksCard, DoneRow |
| 02 evening before samples | `evening ∧ booking.tomorrow` | tile w78 + reminder w30 | `GET` only (narrates; never edits) | SamplePrepCard, ReminderStrip, BookedRow |
| 03 care-team question | `question.status=waiting` | tile w74 `2×2 hot`, verbatim text | `POST /me/questions/:id/answer` (Yes seeds med_watch step 2) | TeamQuestionCard, DoneRow |
| 04 new-medicine watch | `med_watch.active` | tile w72 step-aware | `POST /me/med-watch/step{1,2}` | NewMedCard, DoneRow |
| 05 temperature | `temp.due` | tile w75 `1×4 hot` (exact silhouette) | `POST /me/temperature` | TemperatureCard, DoneRow |
| 06 badge day | dose answer hits {1,7,30,100,365} | tile w99 suppresses flash | server-computed in checkin tx | BadgeCelebrationCard, BadgeShelf, MilestoneHero, LevelRing |
| 07 voice health question | transcript classified `health` | overlay `voiceResult:health` → tile w70 | `create_handoff` tool | VoicePop, HandoffCard, ReceiptStrip |
| 08 sick-day triage | transcript classified `sick` | overlay → flash w90 → vomit w76 → temp w75 chain | `POST /me/symptom-notes` (chains server-side) | VoicePop(noted rows), VomitCheckCard |
| 09 all clear | negation of every trigger | fallback tile w−1 `2×2 calm` | none | AllClearCard |
| 10 first-time tour | `checkins=0` or "show me around" | overlay `tour` steps 0-4 | `POST /me/tour/complete` | TourLayer, coach-mark |
| 11 voice command routing | any request | overlay matched/unmatched → workflow | `request_new_workflow` tool; router executes via plan | VoicePop, CommandResultPop, HandoffCard |
| 12 diary entry | transcript classified `diary` | overlay → flash w90 → diary w69 (+ chains) | `share_diary_entry` tool; `POST /me/med-watch/step2` seed | DiarySharedCard, VoicePop(diary) |

---

## 11. Testing and verification

| Layer | Test | Tool |
|---|---|---|
| Contract | fixture snapshot → expected `HomePlan`; invalid plans → fallback | jest, `packages/ui-schema` golden files from the prototype's 11 scenarios |
| Invariants | §4.6 property tests (one-hot-question, weights order, badge thresholds, verbatim diffs) | fast-check property runs |
| Runtime | `npx copilotkit verify --round-trip --runtime-url http://<LAN_IP>:8200/api/copilotkit --agent ui_agent` | CopilotKit CLI (CI gate) |
| Planner | prompt + validators: each scenario yields the workflow's documented stack plan | jest against mock `get_due_items` |
| Data API | JWT `aud` enforcement, consent-scope tests, field-manifest minimums, audit-row assertions, tx badge test, `eventId` dedup | supertest against the compose `data-api` |
| DB roles | `kinetic_agent` cannot DDL, cannot delete `audit_log`, cannot read ungranted schemas; `migrations` job idempotent | psql smoke script in CI |
| Compose | fresh-clone boot: `docker compose up` → both `/healthz` green → QR prints LAN IP | CI smoke (docker available) |
| Device | screencap per scenario + `adb logcat -d -s ReactNativeJS:E` clean, over the hotspot path | adb (CI: emulator matrix; LAN path manual) |
| Grounding | KnowledgeInspector diff: plan references ⊆ snapshot facts | on-device dev harness |
| Offline | airplane-mode check-in → queued → flush on reconnect → badge/chain correctness at sync time | jest + device manual |
| Security | `.env` gitignored, no `DATABASE_URL` in the runtime container env, LAN reachability of `db` **fails** | compose config checks |

---

## 12. Monorepo layout

```
Agentic_Kinetic/
  apps/mobile/                 Expo RN app (Android .apk)            ← §5
  services/runtime/            CopilotKit Runtime + agents + prompts  ← §6
  services/data-api/           Fastify + node-cron + audit            ← §7, §8
  packages/ui-schema/          zod HomePlan/Action/Context contract   ← §4.2
  packages/design-tokens/      prototype tokens → RN theme            ← §5 tokens
  deploy/
    docker-compose.yml         db + migrations + data-api + runtime   ← §9.1
    db/init/                   01-roles.sql (kinetic_agent) + seed
    .env.example               DB_PASSWORD · MIGRATOR_PASSWORD · AUTH0_TENANT · LAN_IP
    qr.sh                      prints pairing QR (LAN IP) after compose-up
  plan-phone-app/              this doc, workflows/, prototype/
```

---

## 13. Build phases

| Phase | Ships | Exit proof |
|---|---|---|
| **P0** skeleton | monorepo, tokens, ui-schema, **compose stack (`db` + roles + migrations) up on the laptop**, runtime + data-api containers green, `verify --round-trip`, Metro/polyfill wiring, QR pairing script | `docker compose up` → both `/healthz` green; round-trip green from laptop |
| **P1** data + identity | Data API + audit + offline dedup, Auth0 user auth + delegated tool calls, server-address pairing in-app | phone on hotspot: chip tap → audit row + snapshot change; airplane-mode tap flushes later |
| **P2** core loop | ui_agent planner + compose_home + registry; workflows 01, 09, done rows, sub tiles | morning → answer → thanks → all-clear, on device over the hotspot |
| **P3** voice + router | hold-to-talk, STT, router agent, workflows 07/08/11/12 chains | sick-day voice → confirmed symptoms → vomit+temp chain |
| **P4** growth surfaces | workflows 02/03/04/05 scheduling, 06 badges, 10 tour, **reminder sync + notifee local notifications** | badge day celebration; evening-before takeover; lock-screen-style local notification logs a dose |
| **P5** polish + demo kit | seeded `.apk`, scenario drawer tuning, 11-scenario walkthrough, optional hosted appendix exercised once | demo script runs end-to-end from a cold laptop + phone on a hotspot; §11 table green |

---

## 14. Open decisions and risks

| # | Item | Status |
|---|---|---|
| D1 | ~~Model provider & OpenRouter posture~~ — **resolved**: BYOK primary (Settings screen token, `x-model-key`), env key fallback | decided (§9.3) |
| D2 | ~~Device connectivity~~ — **resolved**: hotspot LAN primary; `adb reverse` + emulator fallbacks; QR + server-address pairing | decided (§9.4) |
| D3 | Notifications — **default: local (notifee) now, FCM shapes preserved for swap-in** | confirm at P4 |
| D4 | STT provider (on-device vs cloud proxy) — decide in P3 with device-mix data | open |
| R1 | **Laptop/hotspot unreachable** — top operational risk of local-first: mitigated by offline queue + last-valid-plan + server-side reward recompute (§5.6, §7.3) | mitigated |
| R2 | **Hotspot IP drift** — QR re-pair one tap; `/healthz`-gated; mDNS noted as future convenience | mitigated |
| R3 | Cleartext HTTP on the demo `.apk` — scoped network-security-config; acceptable for a research-prototype build; removed in any hosted flavor | accepted |
| R4 | CopilotKit RN fast-moving (`useRenderTool` shim removal, threads pending) — pin versions; ledger §5.1 in CI | mitigated |
| R5 | LLM planner drift — validators make violations invisible to users and loud in dev | mitigated |
| R6 | Notification delivery depends on a recent sync (no FCM) — documented limitation (§8); demo path unaffected | accepted |
| R7 | Thread continuity (RN `threadId` unsupported) — threads table ready; planner is stateless per run by design | accepted |

---

*Disclaimer carried from the plan docs: research prototype for a hackathon — not a medical device, and it must
not be used to make decisions about the care of a real patient.*
