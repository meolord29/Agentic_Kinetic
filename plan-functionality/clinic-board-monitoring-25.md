# The 25 most important things the clinician Clinic Board should have, from a healthcare stance

Companion to `patient-app-monitoring-25.md`, grounded in the same `handover/` build kit
(AGENTS.md contract, ARCHITECTURE.md, GUARDRAILS.md, MODEL-CARD.md, care-plan-schema,
the clinic-board/build-reference HTML, and `deck-v2/ux/data/backend-capture.json`).
One agent, two surfaces: this is the clinician's half — a web board (1440 wide) over a
kidney-transplant panel where the backend computes and the doctor observes and intervenes.

Context: FDA non-device CDS under 21 U.S.C. § 360j(o)(1)(E) lives or dies on **criterion 4** —
the clinician must be able to independently review the basis of every recommendation, so the
board's job is triage before reading and a complete, cited, reviewable basis for every action
(`agent-pk/docs/GUARDRAILS.md`). The governing line: *the maths is shown in full to the
clinician, who decides.*

---

## A. Triage and decision safety

1. **Tiered triage — the board sorts before the doctor reads** — one act-now card in the full
   gradient frame, today's items soft-framed, steady patients fade to quiet rows; brightness
   is the attention scale, and at most one decision owns the screen at a time. `AGENTS.md §7`
2. **Deterministic gate and a graph-enforced pause** — no language model decides whether to
   escalate (the gate is Python reading `Prediction.crosses_boundary`); the pause is a
   LangGraph `interrupt()` the UI renders and answers, and can neither create nor suppress.
   `AGENTS.md §3.8`, `ARCHITECTURE.md`
3. **Exactly two answers, never a default** — decisions are `"accepted"` or `"declined"` only;
   any other resume answer raises rather than falling through to a silent decline.
   `AGENTS.md §3.9`, `ARCHITECTURE.md`
4. **A deadline on every decision** — "Decide by Sun 09:40" in bold red beside the chip, tied
   to the next dose time so the offer's window is explicit. `AGENTS.md §7`
5. **Never a software-written dose** — no dose amount authored by the software and no
   "change dose" button; the board proposes timing and sampling, never dosing. `AGENTS.md §3.10`

## B. The complete observable basis — criterion 4

6. **Predictions as intervals with their ranges** — median 4.7 (2.5–7.3) labelled a 90%
   *prediction* interval, the quantity a therapeutic range is written against; never a bare
   point estimate. `ARCHITECTURE.md`
7. **Risk as a natural frequency** — the 57-in-100 waffle grid from `probability_below`;
   "57 in 100 chance her next trough is below 5" is readable, "0.5675" is not. `AGENTS.md §7`
8. **Troughs are dots, never joined by a line** — measured values stay discrete points, the
   prediction is a separate range capsule; a joining line would invent data between draws.
   `AGENTS.md §3.11`
9. **Clearance in population context** — the population 90% band (15.8–44.4 L/h), the average
   (26.5), her estimate with its CI (40.5, 33.7–48.7), labelled "approximate" whenever the
   genotype is unknown. `AGENTS.md §4`
10. **Null honesty** — `magnitude_ng_per_ml: null` renders as absence, never 0;
    `variability: null` always arrives with and shows its `variability_unavailable_reason`; a
    missing measure must not read as a reassuring one. `AGENTS.md §3.13`
11. **Attribution of change** — how much is genotype, how much the new interacting drug, how
    much adherence, how much unexplained; direction when magnitude is unsupported.
    `ARCHITECTURE.md`, `GUARDRAILS.md §2`
12. **Multi-sample variability KPIs** — time-in-range 22% and IPV 18% against the 30%
    threshold on bullet bars, flagged only when `ipv_is_high`; judgement rests on profiles,
    not single troughs. `AGENTS.md §7`
13. **Sources behind every claim** — every figure carries its citation and population limit
    (the population model is de-novo, fitted days 5–15, so a maintenance patient is an
    extrapolation, disclosed at point of use). `AGENTS.md §3.12`, `GUARDRAILS.md §4`

## C. Intervening through the board

14. **The sampling offer leads with gain and burden together** — exposure width 36% → 26% and
    "becomes independently checkable" first, 3 fingerstick draws beside them; parameter
    precision stays secondary because it can fall while the real gain rises. `AGENTS.md §4`,
    `ARCHITECTURE.md`
15. **Nothing reaches the patient without acceptance** — accept books the sample she then
    sees in her app; decline flags for review; a proposal nobody agreed to never reaches her
    phone ("Nothing reaches Elena unless you accept"). `AGENTS.md §5B`, `ARCHITECTURE.md`
16. **Question approval flow** — the agent drafts information-gathering questions only (never
    instructions); the clinician Send/Edit approves before anything renders in her app.
    `AGENTS.md §5F`
17. **Action vocabulary in plain words** — flag for review, urgent review, escalate to the
    transplant team become tier-2 cards naming the action in words, never icons alone.
    `AGENTS.md §5A`
18. **Done lines that close the loop** — accept collapses to "You requested extra samples.
    She now sees the booking in her app" with a green "Booked · Sun 11 Oct 09:40" chip;
    decline reads "Not now · flagged for review"; the next item takes the frame.
    `AGENTS.md §5B`

## D. Failure and edge handling

19. **Explicit HTTP failure behaviour** — 409 re-runs evaluate instead of retrying the answer;
    422 shows its detail in review style; 500 shows "Could not be evaluated", never steady.
    `AGENTS.md §5B`, `AGENTS.md §10.6`
20. **`review_required` is its own outcome** — a record that could not be evaluated is never
    steady and never an absent escalation; each run clears prior outcomes so no stale booking
    survives; the board branches on `status`, never on which fields are present. `AGENTS.md §3.13`,
    `ARCHITECTURE.md`

## E. Workload, usability and access

21. **View presets for panel scale** — "Actions and key numbers" hides detail, charts, sources
    and steady rows while keeping every action and deciding number; the board stays usable
    from a 12-patient demo to a real clinic. `AGENTS.md §8`
22. **Redundant coding beyond colour** — pip shapes, words, bold and arrows carry every tier
    and out-of-range signal so greyscale still reads; deadline red 5.57:1, out-of-range
    magenta 6.32:1, no text on the gradient. `AGENTS.md §9`
23. **Accessible charts and restrained motion** — every chart carries an aria-label spelling
    out each value, every dot has a tooltip (date, measured or predicted); animations play
    once, under 5 s, and stop under reduce-motion. `AGENTS.md §9`

## F. Accountability and provenance

24. **No clinical figure computed in the frontend** — every number comes from the clinician
    response (`prediction`, `clinician_context`, `clinician_view`), with a data-to-screen
    mapping validated against `backend-capture.json`; the browser adds nothing and rounds
    nothing. `AGENTS.md §3.14`
25. **Decision audit** — timestamped clinician identity on the board; every evaluate/decision
    access to patient data is logged with actor and purpose and returns only declared fields
    (`agent_pk/compliance/`); on-screen reviewability is what keeps the product on the
    non-device side of the line. `GUARDRAILS.md §2, §5`, `MODEL-CARD.md`

---

**Out of scope by contract:** the mood card ("How she says she's been · Send PHQ-2") is
labelled FUTURE DEVELOPMENT, and "Ask about a patient" search is a static placeholder with no
backend — neither is in the first build (`handover/README.md` Scope, `AGENTS.md §7`).

**Disclaimer:** Agent PK is a research prototype built for a hackathon — not a medical device,
not cleared or approved by any regulator, and it must not be used to make any decision about
the care of a real patient. (`agent-pk/docs/GUARDRAILS.md §9`)
