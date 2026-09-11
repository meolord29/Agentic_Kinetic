# AGENTS.md — Agentic Kinetic build contract

Give this file to your coding assistant before any prompt. It is the complete contract for building the
**patient app** and the **Clinic Board** against the backend in `agent-pk/`. The human-readable version,
with diagrams and full payloads, is `deck-v2/ux/build-reference.html`; the visual references are
`deck-v2/ux/screens/patient-widget-final.html` and `deck-v2/ux/screens/clinic-board-final.html`
(open both in a browser — every option has a switch).

**Precedence when sources disagree:** this file → `build-reference.html` → the two HTML boards → anything else.
**Never invent copy, numbers, fields or buttons.** If something is missing, leave a `TODO` and ask.

---

## 1. What you are building

One agent, two surfaces, one synthetic patient (Elena Cruz). No real patient data exists anywhere.

- **Patient app — widgets, not a chat.** The agent decides what is big: what is due now is one large widget
  with a gradient edge, what comes next is a row, everything else is a small tile, done items shrink to a
  done row. No chat box. She talks by holding one button ("Type instead" behind it). Phone frame 390×844.
- **Clinic Board — cutting through the noise.** The board sorts before the doctor reads. The one action to
  take now gets the full gradient frame; what can wait until later today gets a soft frame; steady patients
  fade back. Web, 1440 wide.

**Stack** (`agent-pk/handover/ARCHITECTURE.md`): backend = FastAPI + LangGraph, built and tested. Clinician
UI = React/Next.js with CopilotKit (AG-UI over SSE). Patient UI reads a plain HTTP route and never mounts the
agent. The architecture doc specifies Next.js for both views; earlier briefs targeted Android (Compose) for
the patient app. The contract below is identical either way — choose the platform, then follow the contract.

## 2. Run the backend first

```bash
cd agent-pk
python3.11 -m venv .venv && . .venv/bin/activate
pip install -e ".[api]"          # pins live in pyproject.toml; do not float them
python -m pytest tests/ -q       # ~12 min; -m "not slow" while iterating
python -m uvicorn agent_pk.api.app:app --reload
```

`deck-v2/ux/data/backend-capture.json` holds real responses from this backend for Elena. Build against it
before wiring live calls.

## 3. Rules that never change (regulatory design — enforced in Python; do not undo them)

Patient app:
1. **Never mount the agent in the patient app.** Read `GET /api/patient/view` only: no AG-UI stream, no shared
   state, no agent thread. Agent shared state reaches every client on a thread, rendered or not.
2. **Never send a clinician payload to the patient app and hide fields.** A hidden field is still on the wire.
3. **Never show:** a drug level, a prediction, an interval, in/out of range, which way a level is moving, dose
   advice, an interaction verdict, urgency, a countdown, anything about the kidney. Do not display `own_results`.
4. **No digits in software-written patient text.** Exempt: the clinician's own plan text, her own doses and
   times, booked times, phone numbers.
5. **A health question is never answered.** It becomes the handoff widget and goes to the care team.
6. **Instructions reach her only in her clinician's own words.** Unapproved questions never render.
7. **Every check-in answer gets identical thanks and +1.** No streaks, leaderboards, on-time bonuses, random
   rewards, or sad reaction to "Missed it".

Clinic Board:
8. **No language model decides whether to escalate.** The gate is deterministic Python. The pause is a
   LangGraph `interrupt()`; the UI renders it and answers it, and can neither create nor suppress it.
9. **Answers are exactly `"accepted"` or `"declined"`.** Never default.
10. **Never a dose amount written by the software**, and no "change dose" button.
11. **Never a line joining measured troughs.** Troughs are dots; the prediction is a range capsule.
12. **Never a number without its range, never a claim without its source** behind "Sources".
13. **`review_required` is never shown as steady. `magnitude_ng_per_ml: null` is never 0. `variability: null`
    always shows `variability_unavailable_reason`.**
14. **Never compute a clinical figure in the frontend.** Every number comes from the clinician response.

## 4. API contract (built — `agent-pk/src/agent_pk/api/app.py`)

| Route | Body | Returns |
|---|---|---|
| `POST /api/clinician/evaluate` | `{"thread_id": "demo-patient-a"}` | one of three outcomes · 422 malformed case |
| `POST /api/clinician/decision` | `{"thread_id": "…", "decision": "accepted" \| "declined"}` | `complete` · 409 not waiting · 422 bad answer |
| `GET /api/patient/view` | `?thread_id=demo-patient-a` | patient projection only |
| `GET /api/health` | — | status, data class, gate location, action list |

Branch on `status`, never on which fields are present:

```jsonc
{ "status": "awaiting_decision", "offer": {…}, "prediction": {…},
  "variability": {…} | null, "variability_unavailable_reason": "", "clinician_context": {…} }
{ "status": "review_required", "stage": "prediction", "reason": "…", "clinician_context": {…} }
{ "status": "complete", "clinician_view": {…}, "clinician_context": {…} }
```

- **`offer`:** `question`, `next_dose_time_h`, `offsets_post_dose_h` `[0,1,3,6]`, `fasted_required`,
  `burden.extra_draws` (3), `expected_gain.exposure_width_now` → `expected_exposure_width` (0.364 → 0.258),
  `independently_checkable_now` → `expected_independently_checkable` (false → true),
  `secondary_parameter_precision` (**never lead with this**), `evidence[]`, `answers`.
- **`prediction`:** `time_h`, `median/lower/upper_ng_per_ml` (4.74 / 2.47 / 7.29), `interval_mass` 0.9 (a
  PREDICTION interval), `crosses_below/above/boundary`, `probability_below` (0.5675) / `_above`,
  `usable_fraction`, `haematocrit_known`, `interval_note`.
- **`clinician_context`:** `plan{lower_bound_ng_per_ml, upper_bound_ng_per_ml, band_citation}` (5 / 10),
  `own_troughs[]` (4.035, 4.524, 4.493, 5.97 at 143.75/311.75/479.75/647.75 h), `own_curve_samples[]`,
  `own_doses[]`, `target_time_h`, `next_dose_time_h`, `population_reference{label, unit, typical, lower,
  upper, interval_mass, genotype_known, source, source_url, population_limit}` (26.5 / 15.83 / 44.36 L/h).
  When `genotype_known` is false the range is built around a mixed-genotype prior and is approximate:
  label it "approximate" on the clearance line.
- **`clinician_view`** (complete only): `action`, `prediction`, `parameters[]` (CL/F 40.50, 33.66–48.74 L/h),
  `attributions[]`, `evidence[]`, `n_observations`, `calibration_note`, `proposed_sampling` (after accept),
  `variability{ipv_percent 17.69, ipv_is_high, time_in_range_percent 21.91, n_samples, span_h}`,
  `variability_unavailable_reason`.
- **Patient view:** `reference_instant_utc` ("2026-09-12T09:40:00Z"), `patient_view{message, body,
  plan_text_from_clinician, own_doses, own_results, next_sample}`. **`next_sample` is null until a clinician
  accepts.** Messages: `nothing_to_do`, `sample_scheduled`, `contact_your_team`, `evaluation_may_be_helpful`
  (bodies verbatim, see build-reference §6). `clinician_notified` is never served.
- **Times are hours since `reference_instant_utc`.** Render local times from it. 696 h = Sun 11 Oct 09:40;
  719.75 h = 12 Oct; troughs start 18 Sep.

Demo limits: one thread `demo-patient-a`; in-memory checkpointer (restart loses a pending offer); per-process
locking; no auth by design. Run uvicorn once by hand before the demo.

## 5. Actions, end to end

**A. Doctor opens the board.** `POST evaluate` per patient.
- `awaiting_decision` → tier-1 decision card (one per board).
- `review_required` → tier-2 "Open [name]'s record" card with `reason` as focus text (tier 1 if nothing else
  needs a decision). Never counts as steady.
- `complete` + `action == "no_action"` → steady row. Other actions → tier-2 card naming the action in words.

**B. Doctor decides.** "Request extra samples" → `POST decision {"decision":"accepted"}`; disable both buttons
while pending. 200 `complete` → card collapses to tier-3 done line "You requested extra samples. She now sees
the booking in her app." + chip "Booked · Sun 11 Oct 09:40" + "Open"; next item takes the full frame.
"Not now" → `"declined"` → done line "Not now · flagged for review". **409** → re-run evaluate and redraw,
never retry the answer. **422** → show detail in review style. **500** → "Could not be evaluated", never steady.

**C. Elena opens the app.** `GET patient/view`. `sample_scheduled` → row "Booked by your care team · Sun 11 Oct ·
Fingerstick samples", and the evening before, the big timeline widget (offsets → "Before dose · 1 h · 3 h ·
6 h"; `fasted_required` → "Fasting."). `contact_your_team` → care-team widget is big, `body` verbatim.
`nothing_to_do` → no booking widget.

**D. Check-in — NEW route.** Chips "Took it" · "Took it late" · "Missed it" · "Not sure" → `POST /api/patient/log
{thread_id, answer: "taken"|"late"|"missed"|"not_sure", dose_taken_at?}`. Answer shrinks to done row
("Morning dose · Logged · late"); Thanks widget; +1 check-in; level ring advances; next item moves up.

**E. Hold to talk — NEW.** Show "You said" + waveform + her words. A language model extracts ONLY typed fields
(`dose_taken_at`, `food_within_window`, `minutes_dose_to_nearest_meal`, `meal_size_vs_usual`
lighter|usual|heavier|much_heavier, `typical_day`; see `agent-pk/handover/PATIENT-REPORTED-DATA.md`) — sample
annotations for the clinician, never model inputs. "Here's what I noted" rows "Dose" · "Food" · "Typical day?"
each with "Change" (allowed values only); "Looks right" logs (flow D); "Say it again" restarts. Transcript
only — never analyse the voice itself.

**F. Question approval — NEW.** Agent drafts an information-gathering question → tier-2 "Send Elena this
question?" with the draft as focus text → Send / Edit → `POST /api/clinician/question {thread_id, text,
answers, approved_by_clinician: true}` → patient big widget "Your care team asks" + text verbatim + "Yes" ·
"No" · "Not sure". Never drafts instructions.

**G. Health question — NEW.** Any health/medicine question → handoff widget: "That's one for your care team.
I've sent your question to them and they'll reply here." + "Call your care team". Never answered.

## 6. Patient app screens (copy is exact)

Header on every screen: logo mark 38px · "Hi, Elena" (evening: "Good evening, Elena") · date · level ring 48px
("L2") · menu (always: "Call your care team", "This app uses AI").

1. **Now** — eyebrow "Now · morning dose" · "How did this morning's dose go?" · "Every answer counts the same." ·
   2×2 chips. Row booking. Tiles "Badges · 1 more check-in to First month", "Your care team · Call or message".
   Hint "Hold to talk".
2. **Thanks** — done row · "Thanks for telling us!" · "Your care team now has the full picture." · "+1 check-in" ·
   then "Your care team asks" · "Did you start any new medicine this week?" · "Yes" "No" "Not sure".
3. **Milestone** — brand ring badge 112 · "Badge unlocked" · "First month · 30 check-ins" · "Thirty honest
   check-ins. That's a clear picture for your care team." · shelf of three badges · row "Your care team asks ·
   1 question waiting".
4. **Voice** — "You said" card · "Here's what I noted" rows · "Looks right" · "Say it again" · hint "Type instead".
5. **Timing** — "Tomorrow · booked by your care team" · "Fingerstick samples · Sun 11 Oct" · timeline · "Fasting.
   I'll walk you through each one." · "You asked" + her question + handoff + "Call your care team".
6. **Hard days — FUTURE DEVELOPMENT, do not build.**

**Brand ring badges** (copy the `AKB` generator from `patient-widget-final.html`): 120 viewBox; ring r55 stroke
4.7, gradient cyan→violet→magenta; inner disc r41 raised; centre = tick path `M40 61 53 74 81 45` or monoline
digits stroked in light `#0891B2→#7C3AED→#C026D3` (dark `#58E5FC→#C164F3→#E554D6`). Earned at 1 (tick), 7, 30,
100, 365, level every 25 ("L3"). Locked = greyscale 35% (62% dark). Every answer counts.

## 7. Clinic Board

| Tier | When | Style | Chip |
|---|---|---|---|
| 1 act now | `awaiting_decision`; else the top remaining item | 2.5px gradient border `125deg #22D3EE→#8B5CF6 55%→#E554D6`, soft wash, glow, padding 32, title 26/700 | "Needs your decision" · gradient circle |
| 2 today | `review_required`, approvals, flags | 1.5px pastel gradient border, white, light shadow | "Needs review" · violet diamond; "Needs approval" · cyan square |
| 3 quiet | steady, done | flat `#F8F7FF`, 1px line, no shadow, muted title 16 | "Steady · 9" · grey dot; "Booked · …" green |

Card anatomy: chip + deadline "Decide by Sun 09:40" (bold `#C81E54`, clock icon) → **action title in bold with thin
300-weight context beside it** ("Request 3 extra samples? · so this estimate can be checked"; "Review: her
troughs are running low · why she is on your list") → focus sentence (the problem/action bold, gradient
underline; violet in tier 2) → deciding data → buttons → 13px context under buttons (hidden by "Supporting
detail") → "Sources".

Frames: (1) Triage — tier-1 Elena card 8 cols × 2 rows with 57-in-100 grid + mini trough chart; right column
tier-2 review + tier-2 approval; tier-3 steady row. (2) One patient — left 5 cols tier-1 decision card
("57 in 100", "Estimate width 36% → 26%", "3 samples", "If not now: the estimate still rests on 4 troughs, and
nothing can check it until post-dose samples exist.", "Nothing reaches Elena unless you accept. The software
never suggests a dose."); right 7 cols tier-2 evidence: trough number line (0–12, below-range zone, band "target
5–10 · her care plan", dots, 12 Oct capsule), clearance number line (0–60, population 90% shaded, "average 26.5",
"her 40.5" whisker — `parameters[0]` exists only after the decision), bullet bars (time in range 0–100 no mark;
variability with 30% mark, flag only if `ipv_is_high`); row below tier-3 timeline. Mood card = FUTURE DEVELOPMENT.
(3) After deciding — Patient B review takes tier 1; Elena becomes a tier-3 done line.

Out-of-range values: bold `#A21CAF` with "↓"/"↑" and the word. "Ask about a patient" search: static placeholder.

## 8. Tokens, type, switches, motion

- **Patient light / dark:** ground `#F3F1FF`/`#0B0F2E` · surface `#FFFFFF`/`#161C4A` · raised `#ECE9FF`/`#1E2560` ·
  line `#DEDAF5`/`#2C3778` · ink `#12143A`/`#EAF4FF` · muted `#545A86`/`#A7B4E0` · btn `#4B35D6`+white / `#58E5FC`+`#0B0F2E` ·
  cyan/violet/magenta `#22D3EE #8B5CF6 #E554D6` / `#58E5FC #C164F3 #E554D6` · accent-text `#0E7490`/`#58E5FC` ·
  done `#15795A`/`#6EE7B7`. Theme follows the device with a manual switch. **No text on the gradient.**
- **Clinic (light only):** ground `#F3F1FF`, quiet `#F8F7FF`, ink `#12143A`, muted `#545A86`, primary `#4B35D6`,
  deadline `#C81E54`, out-of-range `#A21CAF`, band `#E9E5FB`, done `#15795A`.
- **Type:** Poppins (titles, chips, buttons, numbers with tabular figures) + Manrope (body 16/500, context 13
  minimum). Clinic sizes 32/26/20/16/13; weights 300 context, 500 body, 600 labels, 700 action.
- **Switches (patient = feature flags):** theme · progress ring & levels · milestone badges · celebration · mood
  (future) · motion Off / Feedback (default) / Motion graphics (future).
- **Switches (Clinic = doctor view preferences):** View Everything | Actions and key numbers (hides detail,
  charts, sources, steady, mood) · supporting detail · trend charts · sources · steady patients · mood (future) ·
  highlight key text · colour (greyscale; tiers still read from frame weight, words, dot shapes).
- **Motion — build Feedback only:** tick pop 0.5s; level arc draw 0.9s; status dot pulses twice (2×1.2s); Thanks
  circles breathe (2×2.2s); badge pop 0.52s + two ring pulses; talk button ring (2×1.4s); clinic tier-1 frame
  turns once 1.8s. Everything once, under 5 s, off under reduce-motion. **Motion graphics = FUTURE DEVELOPMENT.**

## 9. Accessibility

Colour never the only signal (words + dot shapes + bold + arrows). Text pairs ≥4.5:1; deadline 5.57:1;
out-of-range 6.32:1; badge numbers ≥3:1. Touch targets ≥48px (talk button 66px). Text to 200% without clipping.
Charts carry an accessible label with every value; each dot has a tooltip (date, measured or predicted).

## 10. Tests you must write

1. Patient bundle and network log contain no clinician field (search responses recursively for `prediction`,
   `parameters`, `attributions`, `probability_below`, `clinician_context`).
2. No software-written patient string contains a digit (named exemptions only).
3. The four check-in answers produce identical Thanks and +1.
4. `next_sample: null` never renders a booking widget, including after "Not now".
5. `review_required` always renders a card and never increments steady.
6. A 409 from decision re-runs evaluate instead of retrying.
7. No path joins measured troughs on any chart.
8. An unapproved question never renders in the patient app.
9. Reduce-motion and Motion Off leave no running animation.

When a screen is done, screenshot it, compare with the HTML reference, and list differences before calling it finished.
