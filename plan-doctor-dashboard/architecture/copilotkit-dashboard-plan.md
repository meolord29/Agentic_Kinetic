# Agentic Kinetic — Doctor Dashboard · CopilotKit Plan

> Prototype **v2 (current)**: `../prototype/doctor-dashboard-prototype-v2.html` — the agentic board:
> a `board_agent` re-composes the whole surface per scenario (like the patient app's bento), with a
> working chat that changes both the board and, through an approval gate, her app. v1 (static
> three-column dashboard with phone overlay) is kept at `doctor-dashboard-prototype-v1.html` for
> reference.
>
> Sources: `handover/AGENTS.md` (build contract), `plan-functionality/clinic-board-monitoring-25.md`,
> `plan-phone-app/architecture/architecture-design.md` (runtime, agents, data model),
> `handover/deck-v2/ux/data/backend-capture.json` (every clinical figure on the board).

**What this adds:** a clinician-facing web dashboard where the doctor reviews patient data remotely,
reads an agent-digested summary, acts on recommendations, and composes custom workflows/surveys the
patient answers on the phone app. One agent, now three surfaces — and the doctor's surface is the
only one with a chat, because the doctor is the reviewer, not the reviewed. §11 defines the v2
agentic-board contract and the doctor workflows (dw-01…09).

---

## 1. Scope of the four capabilities

| Capability | What ships | Contract anchor |
|---|---|---|
| **Review patient data remotely** | Tiered triage rail + patient board: trough dots + prediction capsule, number lines with bands, variability bullets, signals from her app (check-ins, answered questions, plan text verbatim) | monitoring-25 #6–13, AGENTS §7 |
| **Digested information** | `compose_digest` generative-UI card: ≤4 findings, each only rearranging backend figures, each with Sources + population limit | AGENTS §3.12/14, monitoring-25 #13 |
| **Actionable recommendations** | `draft_recommendation` → Send/Edit approval card → verbatim instruction widget in her app; plus the existing accept/decline sampling decision | AGENTS §5B/§5F, monitoring-25 #14–18 |
| **Custom workflow/survey** | `compose_survey` → editable draft (closed answer enums + optional free text) → live phone preview → send → she answers in the bento grid → answers card on the board, free text verbatim | workflows 03/04 patterns, monitoring-25 #16 |

Out of scope, unchanged: mood module, motion graphics, "Ask about a patient" search (static
placeholder), any dose authoring.

## 2. Topology (extends the phone-app architecture)

```text
  Doctor (browser, Next.js)                    Patient (RN app)          laptop · docker compose
  ═══════════════════════                      ═════════════════          ═══════════════════════
    Next.js board (React)
    · @copilotkit/react-core ── SSE ────────────────────────────────────► runtime :8200
    · useCoAgent('board_agent')                  │                          CopilotRuntime v2
    · useCopilotReadable(boardContext)           │ headless RN channel       ├─ ui_agent     (patient home)
    · useCopilotAction render/handlers           └────────────────────────► ├─ router       (voice)
    · data board from data-api REST                                        ├─ board_agent  (NEW · this doc)
                                                                            │
                                              data-api :8080 ◄──────────────┘ tool calls · delegated tokens
                                                ├─ existing patient endpoints
                                                ├─ NEW /clinician/* endpoints (audited, clinician token)
                                                └─ Postgres 16 (kinetic_agent role, unchanged)
```

- The web client may use the **full** CopilotKit web API — `useCoAgent` shared state works here
  (the RN-headless limitation in architecture-design §4.3 does not apply).
- Identity A stays Auth0; the doctor carries a **clinician** token with `care:clinician` scope;
  delegated authorization (§3.2 of the phone architecture) applies unchanged — `board_agent` tools
  forward the doctor's token, the data-api projects declared fields and writes audit rows with
  `actor_type: clinician`.

## 3. The `board_agent`

| Responsibility | Never |
|---|---|
| Compose the board's generative UI: digest cards, recommendation drafts, survey drafts | Decide triage/escalation (deterministic gate stays Python, AGENTS §3.8) |
| Rank and phrase what the doctor reads first (tier copy, findings order) | Author or edit care content without clinician approval |
| Surface "why" — citations, population limits, interval notes — from the payload | Compute, round or invent any clinical figure (§3.14) |
| Drive the survey composer (question suggestions inside closed enums) | Send anything to the patient |

`maxSteps` ≤ 4, same as `ui_agent`. Model wiring (OpenRouter BYOK via `x-model-key`) identical.

## 4. Contracts (zod, `packages/ui-schema`)

```ts
export const DigestCard = z.object({
  component: z.literal("DigestCard"),
  findings: z.array(z.object({
    headline: z.string().max(48),
    body: z.string(),                       // may only cite figures present in the payload
    sourceRefs: z.array(z.number())         // indexes into evidence[]
  })).min(1).max(4),
});

export const RecommendationDraft = z.object({
  component: z.literal("RecommendationDraft"),
  text: z.string().min(20).max(320),        // information-gathering words only
  // validator: no dose language, no digits except from exemptions list
});

export const AnswerType = z.enum(["ternary", "scale_1_5", "text"]);
export const SurveyQuestion = z.object({
  text: z.string().min(8).max(140),
  type: AnswerType,
  required: z.boolean(),
});
export const SurveyDraft = z.object({
  component: z.literal("SurveyDraft"),
  title: z.string().max(60),
  questions: z.array(SurveyQuestion).min(1).max(8),
});
```

Delivery mirrors the phone pattern — plan **down** as frontend tools, context **up**:

| Direction | Mechanism (web) | Payload |
|---|---|---|
| ↓ digest / draft / survey | `useCopilotAction({ name:"compose_digest"|"draft_recommendation"|"compose_survey", render })` | the zod objects above |
| ↑ context | `useCopilotReadable` / `useAgentContext` | `BoardContextSummary` (clinician payload digest + signals) |
| ↑ decisions | deterministic REST (never the LLM) | `POST /clinician/decision`, `POST /clinician/surveys` |

Validators run at emit-time and commit-time; a failure logs, shows the fallback card, and flags in
the dev inspector — the same double-check the phone does with `validatePlan`.

## 5. Survey lifecycle and data model

Reuses the `care_questions` lifecycle, generalised to multi-question:

```sql
surveys        (id, user_id, title, author_id → care_team_members,
                status draft|approved|waiting|answered|closed,
                approved_at, sent_at, created_at)          -- a draft never renders on her phone
survey_q       (id, survey_id, ord, text VERBATIM, type ternary|scale_1_5|text, required)
survey_answers (id, survey_id, question_id, answer text|smallint,
                answered_at, client_event_id UNIQUE)       -- free text stored verbatim, never paraphrased
```

Rules carried over verbatim from the phone model: clinician-authored only (§5.7), verbatim relay
(§5.3), silence is a state (unanswered surveys age and surface on the board, never re-asked at the
patient), one approval gate before anything renders, every read audited.

## 6. API additions (data-api, clinician-scoped)

| Route | Purpose |
|---|---|
| `GET /clinician/patients/:id/summary` | board context: clinician payload digest + signals (adherence count, answered questions, diary refs) |
| `POST /clinician/decision` | unchanged — exactly `accepted` \| `declined` |
| `POST /clinician/recommendations` | `{text, approved_by_clinician:true}` → patient instruction widget, verbatim |
| `POST /clinician/surveys` | `{title, questions[]}` → status `waiting` in her app |
| `GET /clinician/surveys/:id/answers` | per-question results; free text verbatim |
| Patient side: `GET /me/surveys` · `POST /me/surveys/:id/answers` | the phone renders it as the big widget; answers offline-queue like all check-ins |

## 7. Guardrails — unchanged, mapped

| Rule (AGENTS) | How the dashboard obeys |
|---|---|
| §3.8 no LLM escalation | tier-1/tier-2 assignment reads `status` from evaluate; `board_agent` cannot create or suppress the interrupt |
| §3.9 accepted/declined only | decision buttons disable while pending; 409 → re-run evaluate, never retry |
| §3.10 never a software-written dose | RecommendationDraft validator rejects dose language; no "change dose" control exists |
| §3.11 troughs are dots | charts render circles + range capsule only (prototype enforces structurally — no line element joins troughs) |
| §3.12 number↔range, claim↔source | every figure on the board carries its interval; every card carries Sources (3 evidence items + population limits) |
| §3.13 review_required ≠ steady · null honesty | Patient B card stays tier-2 with the reason as focus text; `magnitude_ng_per_ml: null` renders as absence, `variability: null` always shows `variability_unavailable_reason`; the board branches on `status`, never on field presence |
| §3.14 no frontend clinical maths | the prototype embeds backend-capture values verbatim; nothing is derived beyond counting logged doses |

## 8. Design language (decision)

The board uses the **phone-app v2 warm palette** (user decision): ground `#F6F2E7`, surface
`#FFFDF8`, ink `#1F3229`, btn/done `#1E7A54`, gradient trio `#5FB4D6 → #52B584 → #E2C488`, Poppins +
Manrope, 20px radii, tier-1 = full gradient frame, tier-2 = pastel gradient border, tier-3 = quiet
raised rows. One addition the warm palette lacks: `--alert #B3402A` (5.6:1 on surface) for
deadlines and out-of-range values — colour never the only signal (arrows, words, bold, dot shapes).

Note: `handover/AGENTS.md §8` specifies a cool clinic palette (`#F3F1FF`/`#4B35D6`). This prototype
deliberately diverges per the user instruction; swapping palettes is a token-only change.

## 9. Prototype → real build map

| Prototype v2 (simulated) | Real build |
|---|---|
| Embedded backend-capture figures | `POST /api/clinician/evaluate` per patient (FastAPI backend already built) |
| `renderBoard(plan)` + closed REG registry | `compose_board` frontend tool → React BoardPlan components |
| Scenario drawer S1–S9 | real backend states + doctor actions; each state change re-plans the board |
| Chat quick chips + keyword parser | `board_agent` chat over AG-UI/SSE — natural language, same intents |
| Approval gate (draft → Send) | `POST /clinician/recommendations|surveys` with `approved_by_clinician:true` |
| "What Elena will see" preview widget | rendered from the same survey payload the phone's `ui_agent` plans from |
| 30-second walk: triage → why → approve → survey → answers → decide | identical, live |

## 10. Build phases

| Phase | Ships | Exit proof |
|---|---|---|
| B0 (done) | v1 static board prototype | full loop walkthrough in a browser |
| B0.5 (done) | **v2 agentic board** (this doc §11): scenario re-composition + chat-driven intents + approval gate | 9 scenarios re-compose; chat intents route; nothing sends without Send |
| B1 | Next.js shell + `compose_board` registry from `/clinician/patients/:id/summary` | board renders Elena from the real backend, re-composing per state |
| B2 | `board_agent` + BoardPlan validators + inspector | plans ⊆ registry, findings ⊆ payload, sources resolve |
| B3 | recommendation + survey flows end-to-end against data-api | chat draft → Send → phone tile → answers card, audit rows present |
| B4 | multi-patient triage, view presets, a11y pass | greyscale + reduce-motion read; aria labels spell every value |

## 11. The agentic board (v2) — BoardPlan contract and doctor workflows

The v2 redesign makes the doctor's surface agentic the same way the patient app is: **the board has
no fixed layout.** A `board_agent` emits a **BoardPlan** — an ordered stack of cards from a closed
registry — and the surface re-composes on every state change. The doctor never navigates; what
needs them *is* the screen (monitoring-25 #1: brightness is the attention scale, at most one
decision owns the screen, done items shrink to done lines, steady rows fade).

### 11.1 BoardPlan (zod, joins `packages/ui-schema`)

```ts
export const Card = z.discriminatedUnion("component", [
  z.object({ component: z.literal("DecisionCard"),  weight: z.literal(99) }),
  z.object({ component: z.literal("ReviewCard"),    weight: z.literal(95), promoted: z.boolean() }),
  z.object({ component: z.literal("DigestCard"),    weight: z.literal(92) }),
  z.object({ component: z.literal("ApprovalCard"),  weight: z.literal(90), draft: RecommendationDraft }),
  z.object({ component: z.literal("SurveyComposerCard"), weight: z.literal(88), draft: SurveyDraft }),
  z.object({ component: z.literal("SurveyAnswersCard"),  weight: z.literal(85) }),
  z.object({ component: z.literal("KeyNumbersCard"),weight: z.literal(60) }),
  z.object({ component: z.literal("WaitingCard"),   weight: z.literal(55) }),
  z.object({ component: z.literal("DoneLine"),      weight: z.literal(50), text: z.string(), chips: Chip[] }),
  z.object({ component: z.literal("AllClearCard"),  weight: z.literal(-1) }),
]);
export const BoardPlan = z.object({
  planId: z.string(),
  patient: z.string(),
  statusChip: z.enum(["Needs your decision","Needs review","Needs your approval",
                      "Reviewing the basis","Composing to her app","Waiting on Elena",
                      "Answers in","Next · needs review","Quiet"]),
  cards: z.array(Card).max(8),
  steady: z.boolean(),
});
```

**Validators** (emit-time and commit-time, like `validatePlan`): at most one gradient hot card;
weights fix the order; every figure ⊆ clinician payload; verbatim fields byte-identical to their DB
rows; a failure → fallback plan (quiet board), never a broken screen.

### 11.2 Scenario → plan table (what re-composes)

| Scenario (state) | Hot card(s) | Board becomes |
|---|---|---|
| S1 `awaiting_decision` | DecisionCard | gradient decision card + faded steady rows |
| S2 `review_required` | ReviewCard | reason as focus; never steady |
| S3 draft pending | ApprovalCard | draft + Send/Edit + "what she'll see" preview |
| S4 doctor asks "why" | DigestCard + KeyNumbersCard | findings with sources, then the complete basis |
| S5 composing | SurveyComposerCard | editable questions + preview + Send |
| S6 survey sent | WaitingCard | done line "she'll answer in her app" + steady |
| S7 answers in | SurveyAnswersCard | per-question results, free text verbatim → Mark reviewed |
| S8 after deciding | DoneLine + ReviewCard promoted | receipt ("Booked · Sun 11 Oct 09:40"); next item takes the frame |
| S9 all clear | AllClearCard | calm quiet board + steady rows only |

### 11.3 Chat — the doctor's control surface for both surfaces

The chat is the one place the doctor *writes*. Intents split by target:

- **Board intents** (act immediately): "why is she on my list?" → S4; "what's quiet?" → S9.
- **Patient-app intents** (approval-gated, AGENTS §3.6/§5F): "ask her a question", "draft a
  recommendation", "send a survey" → the agent drafts → ApprovalCard/ComposerCard takes the frame →
  **Send** → verbatim payload to her app, receipt done line, audit row. The agent never pushes to
  Elena directly; every patient-app change passes through the doctor's Send.

CopilotKit mapping: chat → `board_agent` run → `compose_board(BoardPlan)` for the board and
`draft_patient_payload(...)` tools whose outputs render as ApprovalCards; sending is a deterministic
REST call, not an LLM action.

### 11.4 Doctor workflows dw-01…09 (grounded in clinic-board-monitoring-25)

| # | Workflow | Trigger | Board change | Rules served |
|---|---|---|---|---|
| dw-01 | **Triage sort** — the board sorts before the doctor reads | open board / any state change | plan ordered by weight; ≤1 hot card owns the screen | A1 |
| dw-02 | **Sampling decision** | `awaiting_decision` | DecisionCard; exactly two answers; deadline in bold red; 409 re-runs evaluate; done-line receipt closes the loop | A2–A5, C18, D19 |
| dw-03 | **Review required** | `review_required` | ReviewCard takes the frame with the reason as focus; its own outcome, never steady | D20 |
| dw-04 | **"Why?" — digest on demand** | doctor asks in chat or taps "Why" | DigestCard + KeyNumbersCard: intervals, 57-in-100, clearance in population context, variability KPIs, sources + population limits | B6–B13 |
| dw-05 | **Recommend through approval** | doctor asks for a draft | ApprovalCard with "what she'll see" preview; information-gathering words only; Send → verbatim note in her app | C14–C16, C18 |
| dw-06 | **Ask through a survey** | doctor asks for a survey | Composer (closed enums, ≤8 questions, optional free text) → WaitingCard → SurveyAnswersCard verbatim → Mark reviewed | C16, verbatim relay |
| dw-07 | **Escalate in words** | flags from the action vocabulary | tier-2 cards naming the action in words — flag for review, urgent review, escalate to the transplant team | C17 |
| dw-08 | **Quiet clinic** | preset / greyscale / reduce-motion | "Actions and key numbers" hides charts, sources, detail; tiers still read from frame weight, words, dot shapes | E21–E23 |
| dw-09 | **Audit everything** | every read/send/decision | inspector: context → plan → validators; audit rows `actor_type: clinician`, fields declared, purpose logged | F24–F25 |

*Disclaimer: research prototype for a hackathon — not a medical device; synthetic data only.*
