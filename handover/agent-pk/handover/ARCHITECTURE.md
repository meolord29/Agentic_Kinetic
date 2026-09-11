# Architecture and API contract — for the agent/frontend build

**Read `APPROACH.md` first for what the product does, and `../docs/GUARDRAILS.md` for the rules the
UI is not allowed to break.** This file is the wiring.

> **STATUS, 2026-09-10 — the backend half of this document is now BUILT, and the open decision it
> told you to resolve in hour one is resolved.** The LangGraph graph, the FastAPI surface and the
> two-channel HTTP contract exist, are tested and have been through a lineage-diverse panel. What
> remains to build is the FRONTEND. Sections that described the backend as forthcoming have been
> rewritten in place rather than annotated, because a build partner reading a stale instruction
> executes it; the one thing kept in its original form is the HITL decision, because *which* of
> the three routes was taken and *why* is load-bearing for the regulatory story.

---

## The stack

```
  React (Next.js)                    CopilotKit React            AG-UI events over SSE
  ├── Clinician view  ───────────────  @copilotkit/react-core  ◄──────────────────────┐
  └── Patient view    ───────────────  @copilotkit/react-ui                           │
                                                                                      │
                                       @copilotkit/runtime  (Node, or route handler)  │
                                                    │                                 │
                                                    ▼                                 │
                                       FastAPI + LangGraph (Python)  ─────────────────┘
                                       └── agent_pk  ← BUILT, 319 tests green
                                           ├── pk/          fitting, prediction, calibration
                                           ├── channel/     the two-channel boundary
                                           ├── compliance/  consent, audit, de-identification
                                           ├── interactions/ curated drug/food lookup + LG tool
                                           ├── agent/       ── BUILT 2026-09-10 ──
                                           │   ├── case.py      typed inputs + the two outcomes
                                           │   ├── evaluate.py  every decision, framework-free
                                           │   ├── graph.py     the LangGraph state machine
                                           │   └── demo_case.py loads the committed fixture
                                           └── api/         ── BUILT 2026-09-10 ──
                                               ├── app.py       the two routes
                                               └── serialise.py hand-enumerated JSON
```

**The split between `agent/evaluate.py` and `agent/graph.py` is deliberate and is the same split,
for the same reason, as `interactions/tool.py` against `interactions/langgraph_tool.py`: every
clinical decision lives in plain functions with no framework import, so it stays testable — and
reviewable — with no graph runtime in the way. `graph.py` is sequencing and the pause. It adds no
decision of its own.** Do not move logic into the graph for convenience.

**Package names** (verify versions at install time — pin them, do not float):

| Layer | Package | Status |
|---|---|---|
| Frontend core | `@copilotkit/react-core` | to install |
| Frontend UI | `@copilotkit/react-ui` | to install |
| Runtime | `@copilotkit/runtime` | to install |
| Python SDK | `copilotkit` (extras: `copilotkit[langgraph]`) | **not installed, and not needed by the backend as built** — see below |
| Agent framework | `langgraph==0.6.8`, `langchain-core==0.3.79` | installed, pinned |
| HTTP | `fastapi==0.141.1`, `uvicorn[standard]==0.52.4`, `httpx==0.28.1` | installed, pinned |
| PK core | `agent-pk` (this repo, `src/agent_pk`) | built |

The Python pins live in `pyproject.toml` under two extras — `agent` (the graph) and `api` (the
graph plus the web layer). **The split is load-bearing rather than tidy-mindedness: the graph is
runnable and testable headless, and putting a web framework in the same group as the decision layer
would quietly make that untrue.**

**`copilotkit` (the Python SDK) is deliberately NOT a backend dependency.** The graph is plain
LangGraph and the routes are plain FastAPI, so the CopilotKit runtime binds to them from the Node
side. That keeps the decision layer free of a frontend vendor: if CopilotKit is swapped, nothing in
`agent/` or `api/` changes. Add the SDK only if the frontend spike proves it must live server-side.

**AG-UI** is the open event protocol between agent and UI — chat, state, tool, UI, control and
lifecycle events over SSE. CopilotKit is a first-party AG-UI client for React; LangGraph is a
partnership integration on the server side. You do not implement AG-UI by hand; the CopilotKit
adapter emits it.

**Reference examples to work from** (CopilotKit repo, `examples/`). **CHECK THESE PATHS BEFORE
RELYING ON THEM — an earlier revision of this plan named a starting-point example three times that
did not exist.** Measured 2026-09-08: `examples/showcases/banking` had been renamed to
`enterprise-brex` and its standalone repo archived, and `examples/langgraph-python` had moved under
`examples/integrations/`. Those are findings with a date, not a current directory listing:
- `examples/integrations/langgraph-python` — the backend wiring pattern. **Now of secondary
  interest**: the backend is built, so this is a reference for how the *runtime* connects, not for
  what to write.
- `showcases/generative-ui` — rendering cards from agent output; the pattern for the prediction
  card and the sampling-offer card. **This is the one that still matters most.**
- a multi-channel showcase — the pattern for two different UIs over one agent. Diverge from any
  banking-style example in one place: it gates a view of ONE payload; we emit two different payload
  types on two different routes.

---

## The primitives that matter for this build

| Primitive | Where we use it |
|---|---|
| `useCoAgentStateRender` | Live render of the fit as points land on the curve — the "watch it converge" moment |
| **HITL pause** | **The clinician sampling decision** — the single most important interaction in the demo. **RESOLVED 2026-09-10 and no longer a frontend decision: the pause is a LangGraph `interrupt()` in the graph, so it happens whether or not the frontend supports any particular primitive.** The UI's job is to render the offer and post an answer. See "The HITL constraint" below for what was built and why |
| `useCopilotAction` | Frontend-executable tools: book the draw, open the fingerstick walkthrough, notify the team |
| Shared state | **Clinician sessions only.** The current fit, its exposure interval and its prediction interval. NEVER streamed to a patient session — see the rule below |
| `useHumanInTheLoop` | The v2 tool-based pause available on LangGraph Python. Agent-initiated by default. **Optional here now** — it may RENDER the offer, but it no longer decides whether the offer exists, because the graph already suspended before any tool call. That inversion is the point |

---

## The rule the frontend must not break

**There are two views and they are not two skins on one payload.** The patient view is a
*projection* of the clinician view that structurally cannot carry a predicted number, an interval,
a boundary verdict, an attribution, or any signal of which way a level is moving.

This is already enforced in Python (`agent_pk.channel`). **The frontend must not undo it**:

- The agent emits **two different payload types**. Do not send the clinician payload to the browser
  and hide fields with CSS or a feature flag — a hidden field is still on the wire, and "hidden" is
  one bug away from "shown".
- The patient view renders `PatientView` only: a message from a closed set, the clinician's own
  authored plan text, the patient's own doses and returned results, and an optional appointment.
- **The patient message set contains no digits.** A test asserts this. If a patient-facing string
  in the UI ever needs to interpolate a number, that is a design error, not a formatting task.
- Dose-up and dose-down, and drifting-low and drifting-high, produce the *same* patient message.
  Do not "improve" this by making them distinguishable.

Serve the two views from **separate routes with separate payloads**.

**The patient view never mounts the CopilotKit agent.** This is the rule that makes the paragraph
above true rather than merely intended. CopilotKit shared state is *client-replicated agent state*:
anything in the agent's state object is on the wire to every client on that thread, rendered or not.
So a patient session that mounts the agent has `Prediction` in the browser even if no component
displays it — which is the "hidden field is still on the wire" failure, arriving through the state
channel instead of through CSS.

- **Clinician session:** mounts the agent, receives shared state, renders `ClinicianView`.
- **Patient session:** does **not** mount the agent. It reads `PatientView` from a plain FastAPI
  route. No AG-UI stream, no shared state, no agent thread.
- **Demo routing:** `/clinician` and `/patient` are separate routes. There is no auth in the demo
  and that is a deliberate hackathon scope decision, stated rather than left silent — the channel
  separation is enforced by *what each route serves*, not by who is asking.

**That test is written and it passes** — `tests/test_api.py::test_the_patient_route_carries_no_clinician_field`
and `::test_no_software_authored_patient_string_contains_a_digit`. It was the cheapest guarantee in
the build and it is now a standing one. Two details worth copying if you write the equivalent
assertion in the frontend:

- It searches the response **recursively**, not just the top-level keys. A leak that mattered would
  arrive nested, and a top-level check would pass straight over it.
- The no-digits assertion applies to **software-authored prose only**, and the exemptions are named
  rather than assumed: `plan_text_from_clinician` is the clinician's own words carried verbatim
  under (o)(1)(D), and the patient's own doses, own results and appointment times are their own data
  and logistics. A blanket "no digits anywhere" assertion would be wrong and would be deleted by the
  first person it inconvenienced.

**One more rule the backend now enforces that the frontend must not undo.** A patient message is
served only if it is TRUE of this system. `CLINICIAN_NOTIFIED` says "your transplant team has been
sent an update", and nothing in this build sends one — no mail, no push, no webhook — so
`api/app.py` refuses to serve it and substitutes `CONTACT_YOUR_TEAM`. Two independent verifier
lineages raised that. If you add a notification channel, remove the substitution in the same commit;
if you add a new patient-facing string, it must be true of the system as built, not of the system as
intended.

## The HITL constraint — RESOLVED 2026-09-10. Read this before touching the pause.

**The pause is the pitch. It is now a LangGraph `interrupt()` inside the graph, and that choice is
part of the regulatory argument rather than an implementation detail.**

### What was built, and why it beats all three options this section used to offer

`agent/graph.py::offer_node` calls `interrupt(...)` — but only on a path the deterministic gate has
already taken. The node is reachable **only** because `gate_action` read
`Prediction.crosses_boundary` and returned an escalation, so:

- **The model cannot decide whether the offer exists.** There is no LLM anywhere in that path. The
  frontend may render the offer however it likes; it cannot suppress it, and neither can a model.
- **The run cannot continue until a person answers.** `interrupt()` suspends the graph. This is a
  hard stop in the engine, not a convention the UI is trusted to honour.
- **The preferred route and the fallback became the same code.** A clinician answering through a
  plain HTTP route and a clinician answering through a generative-UI card resume the *same*
  interrupt. So the interaction survives a frontend that turns out not to support the primitive we
  wanted — which, given the vendor's own docs contradicted themselves, was the real risk.

Against the three options this section previously listed: **(a)** is now unnecessary rather than
wrong — `useHumanInTheLoop` may render the offer, but it is no longer what creates it, so the
"agent-initiated" objection dissolves; **(b)** was not needed; **(c)** is effectively what runs,
except that the pause is a graph checkpoint rather than an ended turn, which means the resume is
addressed and cannot be applied to a run that asked nothing.

### The vendor findings that drove it — kept, because they are why this shape was chosen

Verified against CopilotKit's own documentation 2026-09-08, and re-checked against its CLI 2026-09-09:

| Primitive | Status on LangGraph **Python** |
|---|---|
| `useInterrupt` + `langgraph.types.interrupt()` | Docs carried a banner reading **"Not supported on LangGraph (Python)"** while the interrupt-flow page showed a Python example. **The vendor's docs contradicted each other.** A later check found `useInterrupt` unsupported on *both* LangGraph tracks |
| `useHumanInTheLoop` | Available, and shipped in the scaffold's own example. **Agent-initiated** — the model chooses to call a client-side tool |
| `renderAndWaitForResponse` | v1 `useCopilotAction` option. Confirmed present in the repository |

**Why the distinction was never cosmetic.** `gate` is deterministic code and the whole regulatory
argument rests on that: the escalation decision is made by `Prediction.crosses_boundary`, never by a
language model. An *agent-initiated* pause would have made the gate an LLM decision, which is
precisely what `GUARDRAILS.md` forbids and what criterion 4 turns on. Putting the pause in the graph
removes the dependency on any frontend primitive keeping that promise.

Switching to LangGraph **JS**, where `useInterrupt` is supported, was never an option — the PK core
is Python and porting it is the whole build. That is now moot.

### What the frontend still owes

Render the offer payload and post an answer. Nothing more. The payload's shape is in "The HTTP
contract" below, and it leads with the exposure-width narrowing rather than the calibration score —
**do not re-order those on a card.** Calibration is parameter *precision*: it rises in the forecast
and falls once real post-dose points land, so a card built on it promises an improvement and
delivers a drop on stage. The payload carries the calibration figures only under a key that names
them as secondary, and says so in its own text.

---

## Python API contract — what to call

Everything below exists, is typed, and is covered by tests. `from agent_pk.pk import ...`

> **Most callers should NOT start here any more.** `agent_pk.agent` already composes these calls in
> the right order and handles the two failure modes that matter — a degenerate prediction becomes a
> `ReviewRequired` rather than a silent `NO_ACTION`, and a failed offer forecast degrades to a review
> flag rather than losing the crossing that produced it. Re-assembling that by hand is how those get
> dropped. Use `agent_pk.agent.evaluate` for a headless call, `agent_pk.agent.graph.build_graph()`
> for the stateful one, and read this section when you need to know what a returned object MEANS.

### Fitting and prediction

```python
prior_for(Covariates(
    weight_kg=71.0, haematocrit=0.35,
    cyp3a5_expresser=None,            # None = untested; widens AND shifts the prior
    expresser_prevalence=0.30,        # SET THIS DELIBERATELY per serving population
    formulation="advagraf_prolonged_release",      # demo commits to once-daily ER
)) -> PopulationPrior

fit_individual(doses, observations, prior) -> FitResult
    # .parameters (CL/F, V/F, ka)  .covariance  .estimated_ka  .n_observations
    # Absorption is estimated ONLY when >=2 post-dose samples exist. Troughs alone
    # correctly keep it at the prior — that is not a degraded fit, it is the right one.

predict_trough(doses, fit, target_time_h, lower, upper, seed=...) -> Prediction
    # .median_ng_per_ml  .lower_ng_per_ml  .upper_ng_per_ml
    # .crosses_below  .crosses_above  .crosses_boundary   <- the escalation trigger
```

### The calibration story — this drives the demo

```python
profile_calibration(fit, prior) -> float          # 0..1, parameter precision
exposure_uncertainty(doses, fit, start_h=..., end_h=..., seed=...) -> ExposureEstimate
    # .median_ng_h_per_ml  .relative_width       <- SHOW THIS ONE
    # .independently_checkable                   <- False for a trough-only fit

build_sampling_offer(doses, fit, prior, next_dose_time_h=..., seed=...) -> SamplingOffer
    # .n_extra_samples  .calibration_now  .expected_calibration  .expected_gain
    # ^ this is what renderAndWaitForResponse shows the clinician

auc_cross_check(doses, fit, dose_time_h=..., measured_curve=(c0,c1,c3,c6)) -> AucCrossCheck
    # .model_auc  .published_auc  .relative_disagreement  .agrees  .population_limit
    # MUST be fed MEASURED values, never the model's own predictions
```

**Which number goes on screen.** Show `exposure_uncertainty(...).relative_width`, not
`profile_calibration`. Calibration measures *precision* and is **higher on a worse fit**: a
trough-only fit that assumes absorption away scores higher than a curve fit that carries it, while
being the more biased of the two on exposure. **What is pinned by a test is the ORDERING, not any
particular pair of percentages** (`test_the_calibration_figure_can_flatter_a_worse_fit`) — the
exact figures move with the seed, so do not quote a specific percentage in a document or on a
slide unless you generated it and say which seed produced it. Show the calibration figure only as
a secondary "how individualised is this profile" indicator, never as accuracy.

`independently_checkable=False` is the honest answer to *why sample more*: **right now nothing can
check this estimate but itself.**

### Channels

```python
from agent_pk.channel import (
    ClinicalAction, ClinicianView, PatientView, to_patient_view,
    ParameterEstimate, Attribution, EvidenceNote, SampleAppointment,
)
# ClinicianView CANNOT be constructed without parameters and evidence — criterion 4
# as a constructor signature. Build it fully or it raises.
```

### Compliance

```python
from agent_pk.compliance import (
    AuditLog, AccessPurpose, ConsentRecord, ConsentScope,
    assemble_training_corpus, pseudonym, redact_age,
)
# Every read of patient data goes through AuditLog.access(...) — the read IS the log,
# and it returns only the fields you declared.
```

---

## The HTTP contract — what the frontend calls

**This is the interface. Every shape below was captured from the running application on
2026-09-10, not written from memory.** Serve with `uvicorn agent_pk.api.app:app`.

Two channels over four routes, and the split between the channels is the permission boundary
rather than a convenience:

| Route | Channel | What it can produce |
|---|---|---|
| `POST /api/clinician/evaluate` | clinician | a pending offer, a completed view, or a review-required outcome |
| `POST /api/clinician/decision` | clinician | the completed view after an answer |
| `GET /api/patient/view` | patient | `PatientView` only. **There is no code path from this route to a clinician payload** |
| `GET /api/health` | — | liveness, plus the data class and where the escalation decision is made |

Both clinician routes take `{"thread_id": "<string>"}`; `decision` also takes
`{"decision": "accepted" | "declined"}`. `GET /api/patient/view` takes `?thread_id=<string>`.

### `POST /api/clinician/evaluate` — three outcomes, structurally distinct

**They are distinct on purpose: none of the three may be read as another.** Branch on `status`.

```jsonc
// 1. the gate fired and the run is SUSPENDED, waiting on a person
{ "status": "awaiting_decision", "offer": { /* see below */ } }

// 2. the record could not be evaluated. NOT an absent escalation — do not render this as "fine"
{ "status": "review_required", "stage": "prediction", "reason": "<plain English for a clinician>" }

// 3. no crossing, or a decision has been given
{ "status": "complete", "clinician_view": { /* see below */ } }
```

### The offer payload — render it in this order

```jsonc
{
  "kind": "sampling_offer",
  "question": "This patient's predicted trough interval reaches a boundary of their care plan,
                and the current estimate cannot be independently checked. Take extra samples?",
  "next_dose_time_h": 696.0,
  "offsets_post_dose_h": [0.0, 1.0, 3.0, 6.0],
  "fasted_required": true,
  "burden":        { "extra_draws": 3, "note": "..." },
  "expected_gain": { "exposure_width_now": 0.348, "expected_exposure_width": 0.259,
                     "exposure_width_gain": 0.089,
                     "independently_checkable_now": false,
                     "expected_independently_checkable": true },
  "secondary_parameter_precision": { "note": "Parameter precision, NOT accuracy...",
                                     "calibration_now": 0.796, "expected_calibration": 0.790 },
  "evidence": [ { "claim": "...", "source_url": "...", "population_limit": "..." } ],
  "answers": ["accepted", "declined"]
}
```

**Lead the card with `expected_gain`, and put `burden` beside it.** A clinician weighing a request
on a patient's behalf is weighing the whole ask, and a design that shows only the gain understates
it. `independently_checkable_now: false → expected: true` is the honest answer to *why sample more*:
right now nothing can check this estimate but itself.

**Do not lead with `secondary_parameter_precision`, and note the numbers above show why.** In that
captured run calibration went 0.796 → **0.790** — it went DOWN — while the exposure interval
narrowed 0.348 → 0.259, which is the real improvement. Those exact figures move with the seed; the
*ordering* is what is pinned by a test. A card built on calibration promises an improvement and can
deliver a drop on stage.

### `clinician_view` — the recommendation and its complete basis

```
action                          str, one of the ClinicalAction members
prediction                      { median/lower/upper_ng_per_ml, interval_mass,
                                  crosses_below, crosses_above, crosses_boundary,
                                  probability_below, probability_above, usable_fraction,
                                  haematocrit_known, interval_note }
parameters[]                    { label, value, lower, upper, unit }
attributions[]                  { factor, direction, magnitude_ng_per_ml, source }
evidence[]                      { claim, source_url, population_limit }
n_observations                  int
calibration_note                str
proposed_sampling               { start_time_h, offsets_post_dose_h, fasted_required,
                                  concurrent_observations[], total_patient_burden } | null
variability                     { ipv_percent, ipv_is_high, time_in_range_percent,
                                  n_samples, span_h } | null
variability_unavailable_reason  str
```

Four rules for rendering it:

- **`prediction` is a PREDICTION interval, not a credible interval** — what the laboratory will
  report, which is the quantity a therapeutic range is written against. `interval_note` says so in
  the payload; carry that meaning into the label rather than calling it a confidence interval.
- **`magnitude_ng_per_ml: null` is not zero.** It means the evidence supports a direction but not a
  size. Render the absence, never a `0`.
- **`variability: null` always arrives with a non-empty `variability_unavailable_reason`**, and the
  two can never disagree — the type refuses it. **Show the reason.** A missing measure displayed
  without one reads as a reassuring one, which is a defect this project has produced twice.
- **`evidence` is not a footnote.** Criterion 4 makes the reliability of the driving evidence part
  of what must be reviewable, and `population_limit` is where that lives — the adopted model is
  *de novo* while the patient is maintenance, and the panel says so on every screen that uses it.

### `GET /api/patient/view`

```jsonc
{
  "reference_instant_utc": "2026-09-12T09:40:00Z",   // time_h = 0 maps here; render local times from it
  "patient_view": {
    "message": "nothing_to_do",                       // closed enum
    "body": "Nothing for you to do right now. Your next check is on schedule.",
    "plan_text_from_clinician": "...",                // the clinician's own words, verbatim
    "own_doses": [ { "time_h": 0.0, "amount_mg": 12.0, "status": "taken" } ],
    "own_results": [ { "time_h": 143.75, "concentration_ng_per_ml": 4.035 } ],
    "next_sample": null                               // or the appointment object, once ACCEPTED
  }
}
```

**`next_sample` is null until a clinician has actually accepted.** A thread paused at an offer, and
a thread whose offer was declined, both serve `null` — a proposal nobody agreed to must not appear
on a patient's phone as though it were booked.

**The times are hours since `reference_instant_utc`, not wall-clock.** The numeric core carries no
timezone by design, so rendering "Friday at 09:40" is the frontend's job and the reference instant
is the only input it needs.

---

## LangGraph node design — AS BUILT

Keep the graph small; the intelligence is in the PK core, not in the graph. What shipped:

```
START ──► fit ──► predict ──┬─► [degenerate] ─────────────────────────────► END
                            │                    (ReviewRequired — NOT an absent escalation)
                            └─► gate ──┬─► [no crossing] ──────────────► view ──► END
                                       │
                                       └─► [crossing] ──► offer
                                                            │
                                                    interrupt()  ◄── the run SUSPENDS here
                                                            │
                                            ┌───────────────┴──────────────┐
                                       accepts                        declines
                                   SCHEDULE_ADDITIONAL_PK_SAMPLE   FLAG_FOR_REVIEW
                                       + appointment                 no appointment
                                            └───────────────┬──────────────┘
                                                            ▼
                                                          view ──► END
```

Four things about this graph that are load-bearing and easy to undo by accident:

1. **A degenerate prediction ENDS the run; it never reaches the gate.** The gate would have nothing
   to read, and the value it would most plausibly return is `NO_ACTION` — indistinguishable on
   screen from a patient sitting comfortably in range. The run carries a `ReviewRequired` instead,
   and the HTTP layer reports it as its own outcome.
2. **A resume answer that is neither accept nor decline RAISES.** There is no default, because the
   default a fall-through would pick is "declined", which silently suppresses the escalation the
   node exists to raise.
3. **`fit_node` CLEARS the previous run's outcomes at the start of every run**, and `run_complete`
   is the only completeness signal a reader outside the graph may trust. A checkpointed thread keeps
   every key no node rewrote, so the ABSENCE of a `clinician_view` does not mean "not decided yet" —
   after one completed run it is present forever. That is not hypothetical: before the fix, a
   re-evaluated thread served the patient a booked sample while the clinician sat at a fresh
   unanswered offer.
4. **The list of keys to clear is DERIVED, not hand-maintained**, and the module refuses to import
   if a state key is added without clearing it. A hand-maintained list has the same shape as the bug
   it closes — which is exactly how the first version of that fix came to be incomplete.

**`gate` is deterministic code, not an LLM call.** The boundary-crossing decision comes from
`Prediction.crosses_boundary`. A language model may phrase the explanation; it must never decide
whether to escalate.

**Where the LLM belongs:** turning the patient's free text ("took it 9:40, bit late — started
fluconazole yesterday") into typed `DoseEvent` and interaction observations, and phrasing the
clinician-facing summary. Everything numerical is Python.

---

## What is built vs what to build

| | Status |
|---|---|
| PK model, individual fitting, prediction intervals | **Built** (the suite is now 319 tests across the whole package) |
| Absorption estimation + identifiability guard | **Built** |
| Calibration, sampling offer, exposure uncertainty | **Built** |
| Published-equation cross-check | **Built** |
| Two-channel boundary + tests + mutation-tested | **Built** |
| Consent, audit log, de-identification, training gate | **Built** |
| Guardrails doc, model card | **Built** |
| Curated interaction lookup + its LangGraph tool | **Built** |
| **LangGraph graph** (gate, graph-enforced pause, resume) | **Built** 2026-09-10 |
| **FastAPI surface** (two channels, two routes, two payload types) | **Built** 2026-09-10 |
| CopilotKit adapter | **To build** — binds from the Node side; the backend needs no change for it |
| **Clinician UI** (curve, convergence, offer card, basis panel) | **To build** |
| **Patient UI** (logging, fingerstick walkthrough, schedule) | **To build** |
| **Natural-language ingest** (text → typed observations) | **To build.** The seam is marked in `agent/graph.py`; wiring it brings an API key and the `AGENTS.md` secrets contract with it, neither of which this build has today |
| Personal-baseline detection, triage bandit | Designed, not built |
| Exa evidence retrieval | Designed, not built |

**Known limits of the backend as built, so nobody rediscovers them at 2am:**

- **`InMemorySaver` is not durable.** A restart loses every pending sampling offer. Correct for a
  demonstration, wrong for a deployment; `build_graph()` takes a checkpointer so a deployment
  supplies its own.
- **Request serialisation is per-process.** Requests naming one `thread_id` are serialised by a
  per-thread lock, which is correct for one uvicorn process and NOT correct for multiple replicas —
  those need a transactional checkpointer. It moves at the same time as the point above.
- **Checkpoints grow per distinct `thread_id`** and nothing evicts them. Idle *locks* are capped;
  checkpoints are not.
- **There is no authentication**, deliberately. The channel separation is enforced by *what each
  route serves* — the patient route has no code path that can produce a clinician payload — so the
  absence of auth cannot leak one. That is the claim, it was tested hard by two verifiers, and it is
  not a substitute for auth in a deployment.
- **No real server was ever started.** Everything is exercised through `fastapi.testclient.TestClient`,
  which drives the full ASGI app from real threads but binds no socket. **Run `uvicorn` once by hand
  before the demo.**

### Run it

```bash
~/.venvs/agent-pk/bin/python -m pytest tests/ -q     # 319 tests, ~12 min
mypy --strict --python-executable ~/.venvs/agent-pk/bin/python
ruff check --select S,B,F src tests
check-compliance src/agent_pk tests

# serve it
~/.venvs/agent-pk/bin/python -m uvicorn agent_pk.api.app:app --reload
```

**The suite is slow because the sampling-offer forecast simulates 24 futures per call.** While
iterating, `-m "not slow"` skips the one test that runs at the committed demonstration settings;
everything else runs at a reduced count, which is stated in the test file rather than left implicit,
because a forecast averaged over four futures and one averaged over twenty-four are not the same
claim.

`mypy` **needs** `--python-executable` pointing at the venv, or it reports ~24 phantom errors in
`fit.py` that are not real — the system mypy cannot see the venv's numpy. Do not chase them.
