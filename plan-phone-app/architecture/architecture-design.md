# Agentic Kinetic — Phone App · Software Architecture Design

> Source of truth: `prototype/phone-app-prototype-v2.html` (v2 agentic-home prototype), the 13 workflow specs in
> `plan-phone-app/agentic workflows/`, and the healthcare stance docs `plan-functionality/patient-app-monitoring-25.md`
> and `plan-functionality/clinic-board-monitoring-25.md`.
>
> **Target stack:** React Native (Android `.apk`) · CopilotKit React Native (`@copilotkit/react-native/headless` ≥ 1.64.0)
> · CopilotKit Runtime v2 agents in TypeScript · **No user auth** — the demo is a single-user, machine-local
> system; identity collapses to the seeded demo user (§3) · **Postgres 16 in Docker** reached with the agent
> service's *own* least-privilege role.
> **On-device STT:** `whisper.rn` (whisper.cpp binding), `ggml-base` multilingual model bundled in the APK (§5.4).
> **Local-first:** the whole backend is one `docker compose up`; the app runs in an Android emulator **on the
> same Ubuntu machine** and reaches it via the emulator's `10.0.2.2` host alias — a single-box demo, no LAN setup.
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
| P9 | **Local-first, single-box demo** | The entire backend is one `docker compose up` on the demo laptop, and the app runs in an Android emulator **on that same machine** (`10.0.2.2`) — no LAN, hotspot, or second device anywhere in the demo path. The server being unreachable must never block a check-in (offline queue). |

---

## 2. System topology

```text
 ┌────────────────────────────────────────────────────────────────────────────┐
 │ ONE UBUNTU LAPTOP — the whole demo runs on this machine                    │
 │                                                                            │
 │  ┌── docker compose ──────────────────────┐   ┌── Android emulator ──────┐ │
 │  │ runtime :8200  CopilotKit Runtime v2   │◄──┤ release .apk installed   │ │
 │  │   /api/copilotkit (SSE)                │   │ CopilotKitProvider       │ │
 │  │   ├─ ui_agent  (UI planner)            │   │ runtimeUrl               │ │
 │  │   └─ router    (voice/typed intents)   │   │  http://10.0.2.2:8200    │ │
 │  │   no auth — single-user local demo (§3)│   │                          │ │
 │  │   model calls ──► OpenRouter (BYOK)    │   │ whisper.rn STT           │ │
 │  │                                        │   │ (on-device; mic = laptop │ │
 │  │   ▲ tool calls (fixed demo user)       │   │  mic passthrough)        │ │
 │  │   │                                    │   │ notifee local notifs     │ │
 │  │ data-api :8080 ◄── REST 10.0.2.2:8080 ─┼───┤ offline queue (§5.6)     │ │
 │  │   Fastify · node-cron sweep · audit    │   └──────────────────────────┘ │
 │  │   no auth — loopback only              │                                │
 │  │     │                                  │                                │
 │  │     │ kinetic_agent role · least priv. │                                │
 │  │     ▼                                  │                                │
 │  │ Postgres 16 (db) — INTERNAL ONLY       │                                │
 │  │   volume · init.sql · no ports         │                                │
 │  └────────────────────────────────────────┘                                │
 │  ports bind 127.0.0.1 only — nothing leaves this machine                   │
 └────────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Stack decisions (settled)

| Concern | Decision | Rationale |
|---|---|---|
| Mobile shell | Expo SDK + prebuild, Android target, `.apk` via **local Gradle release build** (whisper.rn requires the NDK toolchain anyway) → installed straight into the demo AVD | Config plugins manage cleartext/permissions safely; headless CopilotKit needs no native peers; bare-RN escape hatch stays open |
| CopilotKit client | `@copilotkit/react-native/headless` **≥ 1.64.0** only | Provider + hooks with zero native peer deps (no `expo-document-picker` / `@gorhom/bottom-sheet` pull-in) |
| Agent framework | TypeScript + CopilotKit Runtime v2 (`CopilotRuntime` + agents + `defineTool`) — **user decision** | One language, one deployable |
| Database | **Postgres 16 in Docker** (`db` compose service) — **user decision** | Workflow data is strongly relational and enum-typed (check-in answers, temperature buckets, question approval states); needs transactions for the `logDose → checkins+1 → badge threshold` invariant; local = zero cloud ops for the demo |
| Service hosting | **Full docker-compose**: `db` + `data-api` + `runtime` — **user decision** | One command up; bind-mounted source + `tsx watch` keeps the dev loop fast; reproducible on any laptop |
| Connectivity | App and backend on the **same machine**: emulator → `10.0.2.2` (host-loopback alias) over HTTP; compose ports bind `127.0.0.1` only | Zero network setup and zero external exposure; `adb reverse` stays as a debugging fallback (§9.4) |
| Identity | **None** — dropped (user decision): Auth0 is a cloud dependency, and this product runs entirely on one machine as a single user | The demo path must never touch the internet for identity; the security story lives at the DB-role + audit layer (§3.3, §3.4). Any future hosted run would add real auth first (§9.5) |
| Push/nudges | **Local notifications** (notifee) scheduled on-device from synced reminders; FCM payload shapes documented as future swap-in | Zero Firebase setup; works fully on the single-box demo (§8) |
| STT | **`whisper.rn`** (whisper.cpp binding) — `ggml-base` multilingual **bundled in the `.apk`** — **user decision** | Fully on-device: audio never leaves the device (the strongest form of the privacy line), no cloud-STT proxy and no Google SpeechRecognizer dependency, transcription works even with the backend down. Realtime streaming (VAD) is a documented v2 upgrade (§5.4) |
| i18n | `en` + `zh-Hant` strings from the contract (monitoring-25 #22) | Care plan carries both languages; copy constants are keyed, not hardcoded |

---

## 3. Identity and security architecture

**No user authentication exists — settled decision.** Auth0 was dropped: it is a cloud service, and this
product must run entirely on one machine with zero cloud identity dependencies. The system is single-user by
construction (the seeded demo user, Elena), and every endpoint is reachable only from the machine's loopback.

The original requirement — *"an AI agent that has its own authentication to a database"* — survives intact as
identity **C**: the Data API owns a dedicated, least-privilege Postgres role that no other component (and no
user) ever uses. What was the delegated-token story (A/B) collapses into fixed demo-user attribution.

```text
 Elena (RN app)               runtime :8200                data-api :8080         Postgres (db)
 ══════════════               ═════════════                ══════════════         ═════════════

──────────────────────────────────────────── B · UI CHANNEL — no auth, loopback only ────────────────────────────────────────────
        ├─SSE /api/copilotkit (no credentials)──────────────────►│                             │
        │                                                        │ fixed demo user (§3.1)      │

───────────────────────────── C1 · AGENT TOOL CALLS — attributed, not authenticated ────────────────────────────────────────────
        │                                                        ├─tool call (fixed demo user)─►│
        │                                                        │ get_due_items · create_handoff …
        │                                                        │                             │ field projection + audit row

───────────────────────────────────────────────── C2 · THE SERVICE'S OWN DATABASE IDENTITY ────────────────────────────────────
        │                                                        │                             ├─connect as─────────►│
        │                                                        │                             │ kinetic_agent role  │
        │                                                        │                             │ (pw from .env · scoped grants)
```

### 3.1 Identity A — the user (fixed demo user, no login)

- There is **no login screen, no token, no session**. The RN app carries no credentials at all.
- `data-api` and `runtime` resolve every request to the single seeded demo user (`DEMO_USER_ID` constant);
  audit rows attribute `actor_type: user` to that user.
- The `consent` model (§3.4) still governs what data may leave the machine and in what projection — consent is
  a data invariant, not an auth mechanism, and it stays.
- The prototype's `scr-access` lock overlay remains a **UI affordance only** (local screen lock, §6 build
  ledger) — it guards no data path because the data path has no other user.
- If this system is ever deployed beyond one machine (§9.5), real user auth is a **precondition**, not an
  add-on: the identity seams (per-request attribution in the data-api, per-request user in agent context) are
  kept in the code so an OIDC provider can be introduced without re-shaping the services.

### 3.2 Identity B/C1 — agent tool calls (attributed to the demo user)

1. The agent's server tools (`get_patient_state`, `get_due_items`, `create_handoff`, `share_diary_entry`, …) run
   inside the Runtime container and call the Data API over the internal compose network — no token to forward;
   attribution is the fixed demo user.
2. The Data API enforces **endpoint field projection** (only fields the endpoint declares may leave Postgres)
   and writes an audit row per request (§3.4).
3. Scope checks derived from consent (`care:read`, `research_deid:read` …) are modeled as **endpoint allow-lists
   keyed by consent state** — tested at the moment of use. They are consent rules, not credentials.

> This still makes P4 structural: the agent cannot see fields no endpoint declares, and the API refuses any
> field not declared by the endpoint (monitoring-25 #25). What changed is only *who* is asking: always Elena,
> by construction.

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
- **`db` publishes no ports** — SQL is unreachable from the emulator, the loopback, or anything outside the
  compose network; only the compose network can connect.
- **Cloud escape hatch:** this role-based design ports unchanged to hosted Postgres (Cloud SQL IAM database
  authentication swaps the credential mechanism; roles/grants carry over). See §9.5.

| Identity | Holder | Authenticates to | Credential | Lifetime |
|---|---|---|---|---|
| A · Elena | RN app (fixed `DEMO_USER_ID`) | data-api, runtime | none — single-user by construction | n/a |
| B · session | runtime → data-api | Data API | none — internal compose network | n/a |
| C · service | `data-api` container | Postgres (`kinetic_agent`) | role password from `.env`, scoped grants | static, revocable by role drop |

### 3.4 Consent and audit

- `consents` is an append-only audit table (monitoring-25 #24: revocation recorded, exclusions carried never
  dropped). Consent-state checks read the latest row at request time.
- `audit_log` rows: `(actor_type user|agent|clinician|system, actor_id, user_id, action, fields[], purpose, at)`.
  The Data API middleware writes one row per request from the fixed demo user + endpoint field manifest.
- The de-identified research path reads through a separate projection endpoint that strips identifiers
  before rows leave Postgres; the training path never sees identifiable data.
- Transport on the demo machine is plain HTTP by design (dev/demo); the loopback-only binding, scoped DB role
  and audit trail are the controls that matter. §9.5 notes TLS termination for any future hosted run.

---

## 4. The UI Agent (the critical piece)

### 4.1 Responsibilities and boundaries

| The `ui_agent` … | The `ui_agent` never … |
|---|---|
| receives a state summary (context) and returns **what the home screen should look like** | mutates care data directly (mutations are typed client actions → Data API) |
| sizes every tile (`cols`, `rows`), tints it (`tone`), orders the stack, picks copy from fixed constants | authors questions, answers, tasks, reminders or badge rules (closed enums + server-side rules only) |
| drives overlays (first-time tour steps, voice-popover result states) | answers health questions (router turns those into handoffs, workflow-07) |
| explains nothing in free prose to the user — the chat surface does not exist in the product | sees fields no endpoint declares (field projection, §3.2) |

Its system prompt is a *renderer of the plan docs*: the sizing grid, tone table, stack rules, priority ladder,
reward rules, copy rules and anti-patterns from `gamification-guidelines.md` are embedded verbatim as
instructions, and **mirrored as executable validators** (§4.6) so a prompt miss cannot ship a violation.

### 4.2 The UI Description Contract (`packages/ui-schema`)

One zod schema package is the single contract shared by the server (tool emission + validation) and the client
(frontend-tool parameters + double-check): `HomePlan` travels **down**, `PatientContextSummary` travels **up**
(§4.3). Zod ≥ 3.24 satisfies CopilotKit's Standard Schema requirement.

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
             props: z.object({ step: z.union([z.literal(1), z.literal(2)]) }),
             chips: z.array(Chip).length(3) }),   // step 1 → answer_med_start · step 2 → answer_med_timing (§4.5 registry: 3/3)
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

// The UP-channel contract (§4.3): what the client registers via `useAgentContext`, refreshed on every
// snapshot change. §4.6-3 admissibility is checked against this shape — a tile referencing a fact absent
// here fails validation, so the planner cannot conjure care facts the patient state doesn't carry.
export const PatientContextSummary = z.object({
  generatedAt: z.string(),                                  // ISO 8601
  user: z.object({
    displayName: z.string(),
    daypart: z.enum(["morning", "evening"]),
    dateLabel: z.string(),
    language: z.enum(["en", "zh-Hant"]),
    registered: z.boolean(),                                // workflow-00 gate for the onboarding stacks
  }),
  consent: z.object({
    deidentifiedResearch: z.boolean(),                      // gates `research_deid:read`; own_care is always on
  }),
  progress: z.object({
    checkins: z.number().int().min(0),
    level: z.number().int().min(1),
    levelPct: z.number().min(0).max(100),
    nextBadge: z.object({ n: z.number(), label: z.string(), remaining: z.number().int() }).nullable(),
    unlockPending: z.object({ n: z.number(), label: z.string() }).nullable(), // celebration awaiting dismissal
  }),
  due: z.object({
    dose: z.discriminatedUnion("status", [
      z.object({ status: z.literal("due") }),
      z.object({ status: z.literal("done"), answer: z.enum(["taken", "late", "missed", "not_sure"]) }),
    ]),
    nextSample: z.object({
      booked: z.boolean(),
      when: z.string().nullable(),                          // "Sun 11 Oct"
      tomorrow: z.boolean(),                                // derived: for_date = current_date + 1
      test: z.string().nullable(),                          // "Fingerstick samples"
      fasting: z.boolean().nullable(),
    }),
    temperature: z.object({
      due: z.boolean(),
      reason: z.enum(["scheduled", "sick_day"]).nullable(),
    }),
    teamQuestion: z.object({
      waiting: z.boolean(),
      text: z.string().nullable(),                          // VERBATIM — only present while waiting
    }),
    medWatch: z.object({
      active: z.boolean(),
      step: z.union([z.literal(1), z.literal(2)]).nullable(),
    }),
    vomitCheck: z.object({ waiting: z.boolean() }),
    reminders: z.array(z.object({
      id: z.string(),
      text: z.string(),
      kind: z.enum(["night_before_prep", "checkin_nudge", "booking_reminder"]),
    })),
  }),
  pins: z.object({
    handoff: z.boolean(),                                   // HandoffCard admissibility
    diaryShared: z.boolean(),                               // DiarySharedCard admissibility
  }),
  tour: z.object({ completed: z.boolean(), active: z.boolean() }),
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
   │                  │◄─context + snapshot─────┤                           │
   │                  ├─useAgentContext(...) → runAgent────────────────────►│

   │                  │                         │◄─get_due_items────────────┤
   │                  │                         │ (fixed demo user, §3.2)   │
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
| Runtime unreachable (compose stopped/crashed) | last valid plan stays; check-ins queue offline (§5.6); banner retries with backoff |
| Model provider error/timeout | Runtime returns agent error → `onError` → fallback plan; reminders already synced stay scheduled on-device |
| whisper.rn init/transcribe failure (unsupported ROM, OOM on low-end devices) | mic FAB hides, typed-input path remains (deterministic guard); one context re-init retry, then permanent fallback |

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
| Provider `headers` is resolved **on render**, not per request | unused in the no-auth demo (§3); if any future auth lands, tokens must live in React state → rotation re-renders provider, plus `copilotkit.setHeaders()` on refresh |
| Cloud props (`publicApiKey`/`licenseToken`) unsupported | self-hosted `runtimeUrl` only — by design here |
| No Inspector, no `@copilotkit/voice`, no `threadId` on `useAgent` | §5.5 dev harness; §5.4 own STT; thread scoping deferred (backend threads table ready) |
| Register frontend tools **once per agent** | tool registration isolated in `src/agent/tools.ts`, mounted at App root |
| Android blocks cleartext HTTP in release builds | demo `.apk` flavor allows plaintext **scoped to `10.0.2.2` (demo loopback)** via network-security-config (§9.4); any future hosted build drops it (TLS) |
| `whisper.rn` is a native module (whisper.cpp + NDK) | Expo **prebuild** required (no Expo Go); proguard rule `-keep class com.rnwhisper.** { *; }`; model `.bin` bundled via Metro `assetExts` (§5.4) |
| `whisper.rn` under Jest | `whisper.rn/jest-mock` in unit/CI tests; release-build verification in the emulator is the P3 exit gate (§13) |

#### 5.1.1 Why the CopilotKit quickstart wizard is not part of this build

The `npx copilotkit onboard` quickstart scaffolds a **Next.js web app with built-in agents** — it cannot
scaffold React Native, and `@copilotkit/react-core`'s UI components do not run in RN. The CopilotKit Runtime
itself is a Node server and **cannot run on-device**; it stays in the `runtime` container (§6) and the app
embeds only the headless client. Every quickstart step has a direct RN equivalent already specified here:

| Quickstart wizard step | RN equivalent in this architecture |
|---|---|
| Next.js app scaffold | `apps/mobile` Expo prebuild (§5.3) |
| `CopilotRuntime` + built-in agent framework | `services/runtime` (§6.1): `ui_agent` + `router` as `BuiltInAgent` instances |
| `<CopilotKit runtimeUrl>` chat provider | `<CopilotKitProvider runtimeUrl>` with no auth headers (single-user local demo, §3) |
| Chat UI / `useCopilotChat` | **none — headless by design (P1)**: `useFrontendTool` composes the plan, `useAgentContext` feeds state (§4.3–4.4) |
| Cloud-hosted playground testing | self-hosted only; verification via `copilotkit verify --round-trip` + on-device `KnowledgeInspector` (§9.4) |

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
  App.tsx                      # CopilotKitProvider(runtimeUrl, no auth — §3) → Navigation
  src/
    agent/
      provider.tsx             # runtimeUrl from serverConfig, onError (headers reserved for future auth)
      tools.ts                 # compose_home · compose_overlay  (registered once, app root)
      usePatientContext.ts     # useAgentContext(summary) — re-registered on snapshot change
      useCareRouter.ts         # transcript → router agent (addMessage + runAgent)
    plan/
      store.ts                 # zustand: { plan, commit(), appliedAt }
      validate.ts              # zod + §4.6 invariants (client-side double-check)
      registry.ts              # name → component map (typed, exhaustive)
    screens/                   # Welcome · Onboarding · Home · Milestone · Settings · Lock (local lock UI only)
    components/                # the 17 registry components + Header/FabWrap/VoicePop/TourLayer/Toast/Sheet
    voice/
      whisper.ts               # whisper.rn context lifecycle: lazy init on first hold-to-talk, release on
                               #   background, bundled ggml-base model path, transcribe/cancel wrappers (§5.4)
      useHoldToTalk.ts         # record → on-device transcribe → confirm-before-commit (privacy line always shown)
    config/
      model.ts                 # OPENROUTER_MODEL constant → x-model-id header (§9.3); single source of truth
    data/
      serverConfig.ts          # backend address (§9.4): `http://10.0.2.2` default in the demo flavor,
                               #   Settings override, /healthz probe
      api.ts                   # typed REST client (user token, retry, offline queue §5.6)
      snapshot.ts
      reminders.ts             # reminder sync → notifee scheduling (§8)
    nav/trail.ts               # stack + fallbacks + deep links
    dev/
      ScenarioDrawer.tsx       # the 11 scenarios (morning, evening, question, newmed, temp, badge, health, sick, diary, clear, firsttime)
      KnowledgeInspector.tsx   # agent-knowledge panel: context sent · plan received · violations
```

### 5.4 Voice pipeline — on-device STT with `whisper.rn` (D4 resolved)

`@copilotkit/voice` is not adapted for React Native, and the cloud-STT proxy option is dropped: speech
recognition runs **entirely on the device** (emulator or handset) via `whisper.rn` (whisper.cpp). Settled choices:

- **Model**: `ggml-base` multilingual (~148 MB f16; quantized `ggml-base-q5_1` ~80 MB is the fallback if APK
  size bites) — better accuracy than tiny, zh-Hant-capable, matching the app's `en` + `zh-Hant` stance —
  **bundled in the `.apk`** via Metro `assetExts: ["bin"]`; no first-run download, works fully offline.
- **Recorder**: `react-native-audio-record` → mono 16 kHz 16-bit PCM → WAV (whisper.cpp's required format).

Pipeline:

1. Hold FAB (66 px) → `Listening` state: wave bars, **Release to send**, privacy line
   ("Only the words are kept. The voice itself is never analysed." — now literally true: audio never leaves
   the device), plus the *typed request* field (always-available redundant input, monitoring-25 #23).
2. Release → `whisperContext.transcribe(wavPath, { language })` → **WAV deleted immediately**; only the
   transcript persists (it becomes `voice_notes.transcript`). The whisper context is lazily initialised on
   the first hold-to-talk (avoids startup cost) and released on background; in-flight runs are cancellable
   (`{ stop, promise }`) for **Say it again**.
3. Transcript = message to the `router` agent → deterministic keyword classifier first
   (`parseSymptoms` / `extractDiary` / `COMMAND_RULES` ported verbatim from the prototype), LLM fallback only
   for misses → `compose_overlay(voiceResult)` → **Looks right** commits via typed Data API calls;
   **Say it again** re-records. No commit before confirmation (workflows 07/08/12).
4. A deterministic **Send** control always ends the turn (never silence detection only).

Notes: whisper.rn's realtime `RealtimeTranscriber` (streaming + Silero VAD) is a documented v2 upgrade path —
batch transcription on release is the v1 contract for prototype parity. Under Jest,
`whisper.rn/jest-mock` stands in; the P3 exit test is the **release build in the emulator** — whisper.cpp runs
natively on x86_64 (no ARM translation needed), and `ggml-base` f16 transcription is accepted slower
in-emulator (comfortably fast on real hardware). Because STT is on-device, voice capture and transcription
work with the backend down — only the *router turn and plan* need the runtime.

### 5.5 Dev harness (replaces the RN-missing Inspector)

The prototype's demo panel ships as a debug-only drawer:

- **ScenarioDrawer** — seeds the local `data-api` with each of the 11 demo scenarios' state.
- **KnowledgeInspector** — shows exactly what `useAgentContext` registered, the raw `HomePlan` received,
  validation verdicts, and the current mutation log. This implements the CopilotKit docs' "prove it works"
  strategy on-device: context-in vs plan-out vs pixels-on-screen must agree, because *rendering data on screen
  does not give the agent access to it*.

### 5.6 Offline queue (local-server requirement)

The backend lives in compose on the same machine — it can be stopped, crashed, or restarted at any moment.
The client therefore treats the `data-api` as an eventually-reachable authority:

- **Check-ins and confirmations** (dose, temperature, symptoms, med-watch, question answers, diary, handoffs)
  enqueue locally (MMKV/SQLite) with a client `eventId` (UUID) the moment the user commits them — the UI
  advances immediately on optimistic state (the prototype's instant re-plan).
- **Preference writes** (consent toggles, language, server-address pairing receipt) enqueue the same way with
  `eventId` dedup; the server re-applies them in order at flush time so consent history stays append-only.
- A flush loop retries with backoff; the server deduplicates on `eventId` (unique index) so retries are safe.
- Optimistic entries are visually indistinguishable, but `KnowledgeInspector` (dev) marks "queued · not yet
  acked". Badge thresholds and chains are **recomputed server-side at flush time** from the event's timestamp,
  so the reward invariants (§4.6-4) hold even for late-synced answers.
- The plan store keeps the **last valid plan**; a quiet "reconnecting" chip appears on Home. No tile ever
  prompts the user to "try again" — the queue is the app's job, not hers.

### 5.7 RN rendering & build ledger (prototype → device realities)

The prototype is browser CSS. This ledger names every construct with no direct RN equivalent and the settled
translation — review PRs against it, don't rediscover it:

| Prototype construct | RN translation |
|---|---|
| Bento grid (CSS grid: `grid-auto-rows: 82px`, `grid-column/row: span n`, `dense` flow) | Custom span-aware grid component: fixed 82 px row unit + 12 px gutter, each tile sized absolutely from its plan `layout.cols/rows`; stack order = plan order. `FlatList numColumns` is insufficient (cannot span rows) — the home is a bounded plan (≤ 14 tiles) so a plain mapped `ScrollView` grid is correct |
| `conic-gradient` level ring + animated `@property --p` | `react-native-svg` circle with `SweepGradient` + Reanimated-animated stroke dash; `header.levelPct` drives it |
| Keyframe animations (`enter`, `pop`, `ringpulse`, 45 ms stagger) | Reanimated entering animations; reduced-motion preference renders statically (mirrors the prototype's media query) |
| `backdrop-filter` blur (lock-screen notifs) | skipped — flat translucent surface; cosmetic only |
| Google Fonts CDN (Poppins/Manrope) | `.ttf` assets bundled via `expo-font`, loaded at App root; `--display`/`--sans` become named fonts in `packages/design-tokens` |
| `text-wrap: balance` | unsupported; copy constants are already short (≤ 2 lines at 390 px) |
| `localStorage` (OpenRouter token, Settings) | MMKV — encrypted instance for token + server address |
| Fixed 390×844 phone frame | full-screen device; `react-native-safe-area-context` insets + edge-to-edge status bar |

Build & packaging ledger — the `.apk` checklist (none optional by P5):

| Item | Decision |
|---|---|
| App identity | `applicationId ai.kinetic.patient` (placeholder — confirm before P0) · `versionCode` bumped per build · display name "Agentic Kinetic" |
| Signing | local keystore generated once into `deploy/android-keystore.*` (gitignored), wired via Gradle; `eas.json` `preview` profile builds the `.apk` — no store submission in scope |
| Icon / splash | adaptive icon from the `mark-a` gradient mark; splash = ground color + mark (`expo-splash-screen`) |
| Manifest permissions | `RECORD_AUDIO` (runtime-prompted via the onboarding permissions screen) · `POST_NOTIFICATIONS` (Android 13+ runtime prompt — the permissions screen's notification row) · `RECEIVE_BOOT_COMPLETED` (notifee re-schedules synced reminders after reboot) · `INTERNET` |
| Cleartext | demo flavor `network-security-config` scoped to `10.0.2.2` (loopback) (§9.4); hosted flavor omits it |
| `call_care_team` action | `Linking.openURL("tel:…")` from `care_team_members.phone`; empty number → honest toast ("No direct line stored — I'll pass a message instead") + handoff suggestion. Never a silent no-op |
| Background sync (§8) | `expo-background-task` (WorkManager) 60-min periodic sync, best-effort; foreground sync remains primary (no FCM limitation documented in §8) |
| Lock overlay trigger | app resume (local screen lock — a UI affordance only; no session exists under it, §3.1) or manual lock from the menu sheet. (The prototype's tap-the-clock lock is a demo affordance and does not ship) |
| i18n | `i18n-js` + `en`/`zh-Hant` JSON catalogs in `packages/ui-schema` (keys mirror the copy constants); language from `users.language` |
| Monorepo tooling | npm workspaces + TypeScript project references; single `tsconfig.base.json`; all four workspaces consume `packages/ui-schema` |

---

## 6. Agent layer (`runtime` container)

### 6.1 Service sketch

```ts
// services/runtime/src/server.ts
import { createServer } from "node:http";
import { CopilotRuntime } from "@copilotkit/runtime/v2";
import { createCopilotNodeListener } from "@copilotkit/runtime/v2/node";
import { uiAgent, routerAgent } from "./agents";

const runtime = new CopilotRuntime({
  agents: { ui_agent: uiAgent, router: routerAgent },
});

createServer(
  createCopilotNodeListener({ runtime, basePath: "/api/copilotkit" }),
).listen(Number(process.env.PORT ?? 8200));
```

- Runs as the `runtime` compose service (bind-mounted source + `tsx watch`); publishes `8200` on loopback
  (`127.0.0.1:8200`) — the emulator reaches it via `10.0.2.2`.
- No auth middleware (§3) — the loopback binding is the boundary; every request is attributed to the fixed
  demo user.
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

STT is fully client-side (§5.4): the runtime receives transcripts, never audio — there is no STT proxy on
`data-api`, and no model secret exists on the backend for speech.

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
users            (id, display_name, language, timezone, created_at)          -- single demo user; auth is dropped (§3)
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
    BACKEND (compose · same machine)                          APP (Android emulator · 10.0.2.2)
    ═══════════════════════════════                           ══════════════════════════════════
        │ node-cron (every 5 min) · compute-due sweep:        │
        │   · dose window by daypart      · booking tomorrow  │
        │   · reminder fire times         · stale sweep →     │
        │     missing_after_hours (clinician side only)       │
        ├───reminders rows (fire_at · text · kind)───────────►│
        │                                                     │
        │◄══device sync · GET /me/snapshot════════════════════┤
        │   (app open · resume · hourly bg sync)              │
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
  upcoming reminder (app opened with the backend up, or hourly background sync). The demo path — emulator
  kept running with the app backgrounded — works. FCM remains the future swap for anywhere-push: `data-api`
  already computes the payloads; adding a Firebase project later replaces the notifee scheduler, not the API (§9.5).
- **Stale sweep**: `missing_after_hours` marks are clinician-side only; the patient surface never re-asks.

---

## 9. Local-first deployment and networking

### 9.0 Demo-laptop bootstrap (Ubuntu)

The demo machine is a single Ubuntu laptop — everything (backend compose stack, emulator, app) runs on it.
Baseline already present and verified on the current demo laptop (`anton`): Docker 29.7.2 + Compose v5.5.0,
Node 22.22.1, git, 20 cores, 26 GB RAM, 652 GB disk, KVM-capable CPU with `/dev/kvm` present,
emulator 37.1.11 — **first AVD boot completed in ~24 s**. One-time setup:

| # | What | Command |
|---|---|---|
| 1 | KVM access for the user (emulator acceleration — without it the emulator refuses or crawls) | `sudo usermod -aG kvm $USER` → re-login (`egrep -c '(vmx\|svm)' /proc/cpuinfo` ≥ 1, `ls -l /dev/kvm`) |
| 2 | JDK 17 (Gradle requirement) | `sudo apt install openjdk-17-jdk` |
| 3 | Android cmdline-tools (no full Android Studio needed) | unzip `commandlinetools-linux` → `~/Android/Sdk/cmdline-tools/latest`; export `ANDROID_HOME=~/Android/Sdk`; add `platform-tools` + `emulator` to PATH |
| 4 | SDK packages — **NDK + CMake required**: whisper.rn builds whisper.cpp from source on Android | `sdkmanager --licenses` then `sdkmanager "platform-tools" "emulator" "platforms;android-35" "build-tools;35.0.0" "ndk;27.0.12077973" "cmake;3.22.1" "system-images;android-35;google_apis;x86_64"` |
| 5 | AVD | `avdmanager create avd -n kinetic -k "system-images;android-35;google_apis;x86_64" -d pixel_7` |

Android Studio is an optional GUI alternative for steps 3–5; the CLI path is sufficient. Budget ~12 GB disk
for SDK + system image; the bundled `ggml-base` model adds ~148 MB to the `.apk`.

**First-boot verification & known warnings** (all observed on the demo laptop's live boot — this table is the
bootstrap success check):

**Boot-order rule — the adb server must be running before the emulator starts.** Launch order:
`adb devices` (auto-starts the daemon on `:5037`) → `emulator -avd kinetic -no-metrics` → `adb devices`
again must list `emulator-5554 device`. Starting the emulator first logs
`ERROR: Unable to connect to adb daemon on port: 5037`, and install/screencap/logcat all fail until a server
is started.

| Warning observed | Verdict / action |
|---|---|
| Metrics-collection prompt banner | launch with `-no-metrics` — silences the one-time usage-data prompt permanently |
| `Your GPU drivers may have a bug. Switching to software rendering` (llvmpipe + swangle) | **accepted** — the demo UI is simple and whisper is CPU-bound; try `-gpu host` later only if the desktop feels sluggish |
| `Could not find the Qt platform plugin "wayland"` | cosmetic — falls back to xcb; the window opens normally |
| `Failed to load snapshot 'default_boot'` on first boot | harmless first-boot noise; a snapshot is written on clean shutdown |
| `Increasing RAM size to 2560MB` · boot in ~24 s · `Saving last run QEMU version` | normal behavior — treat as the success signature |
| `The emulator now requires a signed jwt token for gRPC access` | note only — not on the demo path |

**Demo runtime walkthrough — what talks to what, in order:**

1. `deploy/demo.sh` → `docker compose up` (db → migrations → data-api → runtime; both `/healthz` green).
2. `demo.sh` then runs `adb devices` (starts the adb daemon — §9.0 first-boot rule) and boots the AVD:
   `emulator -avd kinetic -no-metrics`; the seeded release `.apk` is already installed. The script exports
   `ANDROID_HOME` and PATH itself and uses absolute `$ANDROID_HOME` tool paths — it never relies on the
   caller's shell environment.
3. App → `http://10.0.2.2:8200/api/copilotkit` (SSE; no credentials — single-user local demo, §3; optional
   `x-model-key` + `x-model-id` BYOK headers, §9.3):
   `useAgentContext` registers state up, `compose_home` / `compose_overlay` deliver plans down.
4. Runtime agent tools → `http://data-api:8080` on the internal compose network → Postgres as `kinetic_agent`.
5. Chip taps / confirmations → REST to `http://10.0.2.2:8080` → offline queue if compose is down (§5.6).
6. Hold-to-talk → recorded on the emulator (laptop mic passthrough) → whisper.rn transcribes **on-device** →
   transcript to the router agent. Notifications fire in the emulator tray via notifee.

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
    # no ports — SQL is unreachable from outside the compose network

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
      PORT: 8080
    ports:
      - "127.0.0.1:8080:8080"                     # loopback only — the emulator reaches it via 10.0.2.2
    volumes:
      - ../services/data-api:/app

  runtime:
    build: ../services/runtime
    command: npm run dev
    environment:
      DATA_API_URL: http://data-api:8080          # internal — never exposed
      PORT: 8200
    ports:
      - "127.0.0.1:8200:8200"                     # loopback only — the emulator reaches it via 10.0.2.2
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

- `deploy/.env` (gitignored; `.env.example` committed): `DB_PASSWORD`, `MIGRATOR_PASSWORD`.
- One command: `docker compose --env-file .env up --build` (or `deploy/demo.sh` for the full demo flow,
  §9.0). Rebuild-on-change is avoided by bind mounts + `tsx watch`; a fresh laptop clone → demo in ~5 minutes
  (image pulls dominate).

### 9.2 Environment matrix

| | demo/dev (the product of this doc) | future hosted (§9.5) |
|---|---|---|
| Where | one Ubuntu laptop: compose + Android emulator (§9.0) | Cloud Run ×2 + managed Postgres |
| App delivery | seeded release `.apk` installed in the demo AVD | internet → HTTPS domain |
| Device network | emulator loopback → `http://10.0.2.2` | internet → HTTPS domain |
| Model auth | **BYOK** OpenRouter token from Settings (primary); env key optional | central key in Secret Manager |
| User auth | **none** — single-user local demo (§3) | real auth is a **precondition** for any public deployment (§9.5) |
| DB credential | `kinetic_agent` role, `.env` | same role model; IAM DB auth optional upgrade |
| Push | notifee local (synced) | FCM |
| Cleartext | allowed, scoped to `10.0.2.2` (demo flavor) | TLS only |

### 9.3 Model provider — OpenRouter BYOK is the primary posture

The prototype already stores a user-supplied OpenRouter token on-device (`ak.openrouter.token`, Settings
screen) — the local architecture keeps that pattern as the default:

| Option | Mechanism | When | Notes |
|---|---|---|---|
| **(b) BYOK — primary** | Settings-screen token sent per request (`x-model-key` header); runtime builds the model instance per run; base URL `https://openrouter.ai/api/v1` | demo/dev | **keyless backend** — no model secret exists on the laptop at all; each demo attendee brings their own key; matches the prototype screen exactly |
| (a) central env key | `OPENAI_BASE_URL` + `OPENAI_API_KEY` env on the runtime container | CI, scripted tests, users without a key | identical code path, env fallback only |
| (c) both *(implemented)* | header overrides env when present | — | runtime agent factory reads `x-model-key` + `x-model-id` → per-request model+model-id; env otherwise |

**Model selection** follows the same header scheme: the app pins the model id once in
`apps/mobile/src/config/model.ts` (`export const OPENROUTER_MODEL = "…"` — value TBD, single source of truth)
and sends it as an `x-model-id` header alongside `x-model-key`. The runtime agent factory resolves the model
as `x-model-id` header → `MODEL_ID` env → built-in default. OpenRouter model strings pass through unchanged
(`provider/model` form).

**Resolved decision** (was pending in v1): local-first makes BYOK the sensible default; the central-key
discussion moves with the hosted appendix (§9.5).

### 9.4 Same-machine demo networking (settled — emulator loopback)

| Path | Runtime URL in the app | When |
|---|---|---|
| **Emulator loopback — primary** | `http://10.0.2.2:8200/api/copilotkit` (data-api `:8080`) | the demo path: `10.0.2.2` is the emulator's alias for the host's loopback, so the app reaches the compose ports with zero network setup |
| `adb reverse` fallback | `adb reverse tcp:8200 tcp:8200` + `tcp:8080` → `localhost` | debugging, or if a build resolves `localhost` directly |

- **Server pairing collapses to a default**: `serverConfig.ts` ships `http://10.0.2.2` in the demo flavor; the
  Settings address field remains as an override, gated by the **`/healthz` probe** on both services before it
  saves. No QR codes, no mDNS, no IP drift — the backend never leaves the machine.
- **Cleartext HTTP**: the demo `.apk` flavor ships a `network-security-config` allowing plaintext **only for
  `10.0.2.2`** — never in a hosted build. No iOS work exists (Android-only target).
- **Compose ports bind `127.0.0.1` only** (§9.1) — nothing outside the laptop can reach db, data-api, or
  runtime; `db` still publishes no ports at all.
- **Emulator notes**: KVM acceleration required (§9.0); **start the adb server before the emulator** (§9.0
  first-boot rule — `adb devices` first, then `emulator -avd kinetic -no-metrics`); the emulator mic is the
  laptop mic (hold-to-talk passthrough); `kinetic://` deep links and notification taps work inside the
  emulator; whisper.cpp runs natively on x86_64 — no ARM translation involved; software rendering (llvmpipe)
  on the demo laptop is accepted (§14 R2).
- **Verification ladder** (per CopilotKit RN docs, no browser/Inspector exists):
  1. `npx copilotkit verify --round-trip --runtime-url http://10.0.2.2:8200/api/copilotkit --agent ui_agent`
  2. on-device screencap (`adb exec-out screencap -p`) + `adb logcat -d -s ReactNativeJS:E` clean
  3. grounding check via `KnowledgeInspector`: plan references ⊆ snapshot facts

### 9.5 Future: hosted appendix (out of scope now, mapped for later)

The service boundaries are drawn so hosting is a re-plumb, not a rewrite. **Precondition: user auth must be
designed before any hosted run exists** — the no-auth demo works only because every byte stays on one machine
and there is exactly one user (§3). The identity seams are kept in place (per-request attribution in `data-api`,
fixed demo user in agent context) so an OIDC provider can be slotted in without re-shaping the services:

| Local | Hosted swap |
|---|---|
| no user auth (single-user demo) | **real user auth (OIDC) first — precondition for anything public**; per-user attribution replaces the fixed `DEMO_USER_ID` |
| `runtime` container | Cloud Run `kinetic-runtime` (min-instances 1, SSE supported, timeout ≥ 300 s) |
| `data-api` container | Cloud Run `kinetic-data-api` behind TLS |
| `db` container + volume | Cloud SQL Postgres — same `kinetic_agent` role model; credential becomes IAM DB auth |
| `.env` secrets | Secret Manager |
| node-cron + notifee | Cloud Scheduler + FCM (payload shapes already computed, §8) |
| BYOK OpenRouter | central key in Secret Manager (or keep BYOK) |
| cleartext loopback | TLS termination; cleartext flags removed from the hosted flavor |

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
| Runtime | `npx copilotkit verify --round-trip --runtime-url http://10.0.2.2:8200/api/copilotkit --agent ui_agent` | CopilotKit CLI (CI gate) |
| Planner | prompt + validators: each scenario yields the workflow's documented stack plan | jest against mock `get_due_items` |
| Voice | fixture WAV → `whisper.rn/jest-mock` transcript → expected router classification; release-build hold-to-talk in the emulator → "You said" confirm (P3 gate) | jest mock + adb |
| Data API | JWT `aud` enforcement, consent-scope tests, field-manifest minimums, audit-row assertions, tx badge test, `eventId` dedup | supertest against the compose `data-api` |
| DB roles | `kinetic_agent` cannot DDL, cannot delete `audit_log`, cannot read ungranted schemas; `migrations` job idempotent | psql smoke script in CI |
| Compose | fresh-clone boot: `docker compose up` → both `/healthz` green → `demo.sh` boots the AVD (§9.0) | CI smoke (docker available) |
| Emulator | screencap per scenario + `adb logcat -d -s ReactNativeJS:E` clean, against the compose backend via `10.0.2.2` | adb (emulator matrix is the primary and CI path) |
| Grounding | KnowledgeInspector diff: plan references ⊆ snapshot facts | on-device dev harness |
| Offline | emulator network-off check-in → queued → flush on reconnect → badge/chain correctness at sync time | jest + emulator manual |
| Security | `.env` gitignored, no `DATABASE_URL` in the runtime container env, external reachability of `db` **fails**, compose ports bound to `127.0.0.1` | compose config checks |

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
    .env.example               DB_PASSWORD · MIGRATOR_PASSWORD
    demo.sh                    compose up → adb daemon → boot AVD → install .apk → seed scenario (§9.0);
                               self-contained: exports ANDROID_HOME/PATH, absolute tool paths
  plan-phone-app/              this doc, workflows/, prototype/
```

---

## 13. Build phases

| Phase | Ships | Exit proof |
|---|---|---|
| **P0** skeleton | monorepo, tokens, ui-schema, **compose stack (`db` + roles + migrations) up**, runtime + data-api containers green, `verify --round-trip`, Metro/polyfill wiring, AVD bootstrap (`demo.sh` skeleton) | `docker compose up` → both `/healthz` green; round-trip green via `10.0.2.2` from the emulator |
| **P1** data + audit | Data API endpoints + audit + offline dedup, server-address default (`10.0.2.2`) + `/healthz` probe | release build in emulator: chip tap → audit row + snapshot change; network-off tap flushes later |
| **P2** core loop | ui_agent planner + compose_home + registry; workflows 01, 09, done rows, sub tiles | morning → answer → thanks → all-clear, in the emulator against the compose backend (`10.0.2.2`) |
| **P3** voice + router | hold-to-talk with on-device `whisper.rn` transcription, router agent, workflows 07/08/11/12 chains | sick-day voice transcribed **on-device** → confirmed symptoms → vomit+temp chain; STT path proven airplane-mode (no network needed for transcription) |
| **P4** growth surfaces | workflows 02/03/04/05 scheduling, 06 badges, 10 tour, **reminder sync + notifee local notifications** | badge day celebration; evening-before takeover; lock-screen-style local notification logs a dose |
| **P5** polish + demo kit | seeded release `.apk` in the demo AVD, scenario drawer tuning, 11-scenario walkthrough, optional hosted appendix exercised once | demo script runs end-to-end from a cold laptop: `docker compose up` → AVD boot → seeded `.apk`; §11 table green |

---

## 14. Open decisions and risks

| # | Item | Status |
|---|---|---|
| D1 | ~~Model provider & OpenRouter posture~~ — **resolved**: BYOK primary (Settings screen token, `x-model-key`), env key fallback | decided (§9.3) |
| D2 | ~~Device connectivity~~ — **resolved**: same-machine emulator (`10.0.2.2` loopback) primary; `adb reverse` fallback; single-box demo, no LAN/hotspot (§9.4) | decided (updated for the emulator pivot) |
| D3 | Notifications — **default: local (notifee) now, FCM shapes preserved for swap-in** | confirm at P4 |
| D4 | ~~STT provider (on-device vs cloud proxy)~~ — **resolved**: `whisper.rn` (whisper.cpp) fully on-device, `ggml-base` multilingual bundled in the APK; cloud proxy dropped (§5.4) | decided |
| R1 | **Backend unreachable** (compose stopped/crashed) — top operational risk of local-first: mitigated by offline queue + last-valid-plan + server-side reward recompute (§5.6, §7.3) | mitigated |
| R2 | **Emulator constraints** — KVM acceleration required (§9.0); adb server must start before the emulator (§9.0 first-boot rule); whisper.cpp runs natively on x86_64 (no ARM translation); `ggml-base` f16 transcription accepted slower in-emulator; demo-laptop GPU driver falls back to software rendering (llvmpipe) — accepted, whisper is CPU-bound (§9.0) | accepted |
| R3 | Cleartext HTTP on the demo `.apk` — network-security-config scoped to `10.0.2.2` loopback only; acceptable for a research-prototype build; removed in any hosted flavor | accepted |
| R4 | CopilotKit RN fast-moving (`useRenderTool` shim removal, threads pending) — pin versions; ledger §5.1 in CI | mitigated |
| R5 | LLM planner drift — validators make violations invisible to users and loud in dev | mitigated |
| R6 | Notification delivery depends on a recent sync (no FCM) — documented limitation (§8); demo path unaffected | accepted |
| R7 | Thread continuity (RN `threadId` unsupported) — threads table ready; planner is stateless per run by design | accepted |

---

*Disclaimer carried from the plan docs: research prototype for a hackathon — not a medical device, and it must
not be used to make decisions about the care of a real patient.*
