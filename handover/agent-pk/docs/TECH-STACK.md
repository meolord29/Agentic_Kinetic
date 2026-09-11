# Agent PK — architecture and build plan

> **This is the TARGET architecture, not a description of what was built.** Several components
> named below — OpenRouter, Trigger.dev, Auth0, Google Cloud Run, openFDA/RxNorm — are the
> intended production shape and are **not** called by the submitted demo. What actually runs is
> **CopilotKit, LangGraph, FastAPI and SciPy**; see [`SUBMISSION.md`](SUBMISSION.md), which is the
> authority on the as-built stack. Read every tool named here as a design decision with a
> rationale, never as a claim of use — and never tick a sponsor tool on the portal, or write one
> into a built-with line, on the strength of this document.

## The shape

```
  patient's phone (group chat / PWA)
        │  free text: "took it 9:40, bit late. started fluconazole yesterday."
        ▼
  EXTRACTION  ── OpenAI structured outputs via OpenRouter ──► typed observation
        │        (the model's ONLY job: words → typed values)
        ▼
  EVENT STORE  ── local-first on device; optional encrypted cloud mirror
        │
        ▼
  PK WORKER  ── Trigger.dev scheduled job, nightly + on-event
        │   1. re-fit this patient's own clearance from their dose/level history
        │   2. simulate forward to the next scheduled draw
        │   3. return an interval, never a point estimate
        ▼
  INTERACTION LOOKUP ── Exa over published PK literature + openFDA label
        │   direction only: does this push the level up or down
        ▼
  DETERMINISTIC GATE  ── plain code. NOT the language model.
        │   does the predicted interval cross a plan boundary?
        ▼
  ESCALATION ── Auth0 async authorization → patient approves → clinician notified
        │
        ▼
  SURFACE ── CopilotKit generative UI: trend chart + escalation card + why
```

## Sponsor mapping

**SCOPE RULED 2026-09-09 (June): four tools IN, four OUT.** Three days to the event and the agent
layer is unbuilt, so the list is cut to what a running demo will actually call. Ticking a tool the
demo does not call is the thing `SUBMISSION.md` already forbids.

### In — the demo calls these

| Tool | What it actually does here | Build risk |
|---|---|---|
| **CopilotKit** | The agent's surface: shared state, the rendered trend chart, the sampling-offer card with its evidence, and the clinician's accept/decline. Not a chat window. | Medium — see the HITL finding below |
| **OpenRouter** | The routing layer in front of the model. Cheap model for extraction, stronger for the weekly summary; one key, provider fallback if a model is down mid-demo. | Low |
| **OpenAI** | The model actually doing structured extraction of a lay report into a typed observation, called *through* OpenRouter. | Low |
| **Exa** | On a newly reported drug, retrieve published interaction evidence for that specific pair and cite it in the escalation. The agent visibly reading the literature. | Low — **seeded and cached**, see below |

### Out — designed, not built. Do not tick these on the portal

| Tool | Why it is cut |
|---|---|
| **Trigger.dev** | The nightly re-fit heartbeat is genuinely the agent acting unprompted, and it is the most painful cut. But it is a whole scheduling integration and a demo can show the same behaviour on a manual trigger. |
| **Auth0** | Async authorization is a lovely story and a second auth integration we cannot land in three days. |
| **Google Cloud Run** | Deployment is not demonstrable value here; run it locally. |
| **Mozilla.ai** | On-device extraction was always marked optional. |

**Exa runs LIVE but SEEDED AND CACHED.** The fluconazole query is issued for real, and its response
is cached to disk so the demo cannot fail on venue wifi or a slow API. This keeps the sponsor claim
honest — the call is real — without putting the pitch at the mercy of the network. Exa's free tier
covers this comfortably (new accounts get $20 credit, ~2,800 searches, plus $10/month).

## The human-in-the-loop primitive — RESOLVED, and not the way we hoped

**This was the open P0 (T4-2). It is now answered from CopilotKit's own documentation.**

The clinician pause is the pitch, and the obvious primitive for it is LangGraph's native
`interrupt()` — pause the graph, ask the human, resume. **CopilotKit does not support that for our
stack.** Both relevant integration tracks carry the banner verbatim:

> "LangGraph (Python) doesn't support Human in the Loop: Interrupts."
>
> "LangGraph (FastAPI) doesn't support Human in the Loop: Headless Interrupts."

We checked `langgraph-fastapi` separately in the hope it was a different track with different
support. It is a different track; it has the same gap.

**What IS supported for LangGraph FastAPI is `useHumanInTheLoop` — the tool-based pattern.** The
model calls a registered client-side tool; the tool renders a component; the human's answer is
returned via `respond(...)` and arrives back at the agent as the tool result.

```tsx
useHumanInTheLoop({
  agentId: "...",
  name: "propose_sampling_schedule",
  description: "Ask the clinician to accept, modify or decline a proposed sampling schedule",
  parameters: z.object({ /* the offer */ }),
  render: ({ args, status, respond }) => (
    <SamplingOfferCard {...args} onSubmit={(decision) => respond?.(decision)} />
  ),
});
```

```python
from langchain.agents import create_agent
from copilotkit import CopilotKitMiddleware

graph = create_agent(model=..., tools=[], middleware=[CopilotKitMiddleware()], system_prompt=...)
```

**And this is a better fit than `interrupt()` would have been — say so rather than presenting it as
a workaround.** Our clinician decision is not an arbitrary mid-execution pause. It is a *discrete,
structured proposal* — here are four sample times, here is what another round would buy — answered
with accept, modify or decline. That is exactly a tool call with typed parameters and a typed
result. It gives us three things `interrupt()` would not:

1. **The decision boundary is explicit in the code.** The clinician's answer is a typed tool result,
   not resumed graph state, so "the clinician decided this" is a value we can log and audit.
2. **It matches the regulatory design.** The agent *proposes*; the human *disposes*. A tool the
   agent cannot answer for itself is a strong structural expression of that.
3. **It survives a restart.** No suspended graph to resume.

## CopilotKit CLI — measured 2026-09-09, and the docs are stale in two places

Measured against `copilotkit@4.9.47` itself, not read off a docs page, because the docs have now
disagreed with the shipped tool twice on this project.

**1. There is no "skip the account" path any more.** The quickstart says you may answer "No" to
Intelligence and get a plain self-hosted setup. The CLI's own help says:

> `-i, --intelligence   Deprecated no-op: Intelligence (durable conversations, persistence,
> insights) ships with every supported framework.`

and

> "Signing in is the one answer no flag supplies: it opens a browser and finishes back at the
> terminal. Run `copilotkit login` first, or a run with no terminal is refused."

So `copilotkit init` REQUIRES a browser sign-in before it will scaffold anything. A free developer
account is enough (logged in 2026-09-09 as the Catalyst Case org). Note the key you get for a
self-hosted setup is a **`publicLicenseKey`**, not the `ck_pub_...` **`publicApiKey`** that Cloud
uses — looking for an "API key" section on a developer account finds nothing, which is a naming
trap rather than a missing entitlement.

**2. `--mock` is real, but not on our framework.** `copilotkit framework list`:

| Framework | Flags accepted |
|---|---|
| `langgraph-fastapi` — LangGraph (Python, FastAPI) | `-i` only |
| `langgraph-py` — LangGraph (Python) | `-i`, **`--mock`**, `--channel` |

`--mock` is a keyless mock model. It would let the HITL wiring be proven with no model key at all,
but only on `langgraph-py`. Our stack is FastAPI (two channel routes), which is also the track
whose `useHumanInTheLoop` support was verified above, so we take the key and stay on
`langgraph-fastapi`. Recorded because if the model key ever becomes the blocker, `langgraph-py
--mock` is the fallback that proves the surface without one.

**3. There IS a no-account path, if it is ever needed.** `@copilotkit/runtime` and
`@copilotkit/react-core` are on npm (1.70.3), and the Python `copilotkit` package is on PyPI
(0.1.96). Wiring those by hand needs no CLI and no sign-in. It is slower and riskier than starting
from a known-good scaffold, which is why it is the fallback rather than the plan.

**Vendor key:** `langgraph-fastapi` reads `OPENAI_API_KEY` from `.env`. We route through OpenRouter
by pointing the OpenAI-compatible client at OpenRouter's base URL — the scaffold's variable name
stays, the endpoint changes. Per the fleet secrets contract the value is read from the admin secret
store, never committed and never a literal in code.

**Residual:** the supported-pattern claim comes from CopilotKit's documentation, not from a running
build. It is not proven until the spike runs. Documentation for this project has already been wrong
once — `examples/showcases/banking`, named three times as the frontend starting point, does not
exist.

## The PK model

**Two-compartment, delayed first-order absorption, oral.** CORRECTED 2026-09-09 — this line said one-compartment, which the model stopped being on 2026-09-08. The structure is not a modelling convenience: the parameter estimates this project uses were fitted to it, and estimates are conditional on the model that produced them, so borrowing published numbers into a simpler form would give values that looked sourced and were not. That is the right level for a short build
and it is defensible: most published tacrolimus population models are one- or two-compartment
with first-order absorption.

Parameters: `CL/F` (apparent clearance), `V/F` (apparent volume), `ka` (absorption rate, fixed
from literature — sparse trough data cannot identify it).

**Step 1 — population prior.** Published population PK models retain, in order of frequency:
CYP3A5 genotype, body size, haematocrit, and days since transplant. Encode those as the prior
mean for `CL/F`, with CYP3A5 expressers carrying roughly 1.5–2× the clearance of non-expressers.

**Step 2 — fit the individual (MAP Bayesian).** Minimise, over the patient's own history:

```
objective(θ) = Σ [ (C_observed − C_predicted(θ)) / σ ]²      ← fit to their own troughs
             + Σ [ (θ − θ_population) / ω ]²                  ← pulled toward the population
```

`scipy.optimize.minimize` on two free parameters. This is the whole "learns your body" claim,
and it is about forty lines. The second term is what stops three noisy troughs producing a
nonsense clearance — with sparse data the prior does most of the work, and that is correct
behaviour, not a limitation to hide.

**Step 3 — simulate forward.** Replay the reported dosing history as input events: a taken dose
is an input, a late dose is a shifted input, a missed dose is no input, a dose vomited within an
hour is no input. Continue to the next scheduled draw.

**Step 4 — return an interval, never a number.** Propagate parameter uncertainty (a few hundred
samples is plenty) and return a credible interval for the predicted trough.

**Step 5 — the gate.** Escalate when the *interval* crosses a plan boundary, not when the point
estimate does. This is the difference between a triage tool and a false-alarm generator.

**Interactions are directional only.** A reported CYP3A inhibitor does not multiply the
clearance by a number we invented. It **shifts the prior and widens the interval** in the
documented direction. The output is "probably drifting up, here is the published evidence, look
sooner" — never "your level will be 14.2".

## Getting C0 and AUC — the honest position

**There is no API that returns a patient's tacrolimus level.** It comes from a lab report.
Entry is manual, or a photo of the report with OCR. Anyone claiming otherwise at a hackathon is
mocking it.

**AUC is not measured either.** Full AUC needs many timed samples. Clinics use the trough as a
proxy, and the correlation is poor — around r² 0.70, and as low as 0.50 in some groups. That
gap is not an inconvenience for us; **it is the reason the product exists.** We estimate AUC
from the fitted individual model rather than measuring it.

**Useful free APIs:**

| API | Use | Notes |
|---|---|---|
| **openFDA drug label** — `api.fda.gov/drug/label.json` | Pull the tacrolimus label's `drug_interactions` and metabolism sections programmatically | Free, no key for low volume. Returns **unstructured prose written for clinicians** — usable as evidence to cite and to feed extraction, not as a machine-readable interaction table. That is precisely why our curated `interactions.json` exists. |
| **RxNorm / RxNav** (NLM) | Normalise whatever the patient types — brand name, misspelling, local name — to a stable drug identifier | Free and live. **But NLM discontinued its Drug Interaction API on 2 January 2024 — permanently, not an outage.** RxNorm, RxClass and RxTerms are unaffected. Do not plan around an interaction endpoint that no longer exists. |
| **DailyMed SPL** | Full structured product labelling | Free |
| **Exa** | The published interaction literature for a specific pair, with citations | Sponsor credit |

Our own `data/interactions.json` (41 drugs, 5 foods, 3 physiological events, all cited) is the
deterministic layer underneath. Exa enriches; it does not decide.

## Data and privacy

- **Local-first.** Observations live on the device by default (IndexedDB). The cloud mirror is
  opt-in and encrypted.
- **Auth0 OAuth** for identity; **async authorization** so the patient approves each disclosure
  to a clinician on their own device.
- **Export belongs to the patient.** The chart renders as self-contained HTML, and the log can
  be written to the patient's *own* Google Sheet through their own token via Token Vault — so
  the record lives in their Drive, not ours.
- **No PHI anywhere in this repository.** Every patient, level and event in the demo is
  synthetic.

## Build order for the day

**Revised 2026-09-09 for the four-tool scope.** Steps 1-3 are DONE (the PK core is built, tested
and panelled through round two; the model was replaced in session 4).

1. ~~Event store + typed observation schema~~ — **done**
2. ~~PK fit and forward simulation against a synthetic patient~~ — **done**, 196 tests
3. ~~Deterministic gate and escalation ladder~~ — **done**
4. **Spike the CopilotKit scaffold** and prove `useHumanInTheLoop` renders and responds end to end
   with a stub payload. Nothing else is worth building until this is proven, because it is the
   pitch and its support status came from docs rather than a run.
5. **Demo fixture** — a synthetic patient whose profile actually crosses the 5–10 ng/mL band, built
   against the new two-compartment model (the old fixture spec was written for the replaced one).
6. **Interactions loader** — read `data/interactions.json`, return direction + mechanism + sources
   for a named drug. Roughly twenty lines; nothing in `src/` reads that file today.
7. **Extraction** — free text to typed observation, via OpenRouter in front of OpenAI.
8. **Exa lookup** for the fluconazole pair, cached to disk on first call.
9. **Wire the sampling-offer card** to the real fit, the real interval and the real offer.
10. Screen-record the demo.

**Cut in this order if time runs out:** 8 (fall back to the cached response and say so), then 7
(hand-type the observation), then 6. **Never cut 4** — without the clinician decision on screen
there is no pitch, only a calculator.

## Gate note

The PK fitting script is Python well over twenty lines and it is the clinical core, so it goes
through `/py-architect` before it is written, and `/triple-check` before the demo. Both are
cheap; discovering the objective function is wrong on camera is not.
