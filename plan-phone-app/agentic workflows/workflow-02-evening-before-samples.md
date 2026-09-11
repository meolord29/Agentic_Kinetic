# Workflow 02 — Evening before samples

> Source: demo scenario `data-sc="evening"` → sample-prep card, weight **78**, layout `{cols:2, rows:3, tone:'hot'}`; reminder strip weight **30**, `{cols:2, rows:1, tone:'info'}` in `prototype/phone-app-prototype-v2.html`.

| | |
|---|---|
| **Trigger** | `daypart === "evening"` **and** `nextSample.booked && nextSample.tomorrow` **and** `dose.status === "done"` |
| **Agent intent** | Prep the user the evening before a care-team-booked sample day: show the schedule, set the night-before reminder, keep the home quiet otherwise. |
| **Entry points** | Home planner (time-of-day switch) · tapping the future booked row on the morning home. |
| **Exit / handoff** | Runs overnight; next morning the agent walks the user through each sample ("I'll walk you through each one" — future sample-day workflow). |

---

## Shared conventions (apply to every agentic workflow)

**Sizing grid** — the home is a 2-column bento grid (82 px row units): `2×N` full-width = the main task; `1×N` half-width = secondary/ambient tiles; 1-row strips = booked events, reminders, done records.

**Tone = importance, never decoration**

| Tone | Class | Use for |
|---|---|---|
| `hot` | `.now` | due right now — gradient border, top of stack |
| `high` | `.t-high` | today's care logistics (booked events, handoffs) |
| `info` | `.t-info` | reminders, FYI strips |
| `game` | `.t-game` | progress, badges, streaks |
| `good` | `.t-good` | thank-you / just-completed confirmations |
| `calm` | — | resting state ("all clear") |
| `done` | `.done` | collapsed record of an answered item |

**Non-negotiable copy rules**
- "Every answer counts the same." — identical chip sizes, zero judgment for any answer.
- The agent never answers clinical questions — it hands off to the care team.
- The agent never invents care tasks. Nothing due → calm resting card only.
- New tiles animate in staggered (`agent-in`, 45 ms per tile). Respect `prefers-reduced-motion`.

---

## 1. Preconditions (agent knowledge)

```json
{
  "clock": "19:40", "daypart": "evening", "dateLabel": "Saturday 10 October",
  "checkins": 31,
  "dose": { "status": "done", "answer": "late" },
  "nextSample": { "booked": true, "when": "Sun 11 Oct", "tomorrow": true },
  "reminders": ["Keep your thermometer by the bed tonight"],
  "teamQuestion": null, "temp": { "due": false, "status": "none" },
  "newMed": null, "handoff": null, "symptoms": [], "vomit": null,
  "flash": null, "unlock": null
}
```

## 2. Home stack plan

| Priority | Widget | Layout | Tone | Weight |
|---|---|---|---|---|
| 1 | Sample-prep card (tomorrow) | `2×3` | `hot` | 78 |
| 2 | Done row "Morning dose · Logged · late" | strip | `done` | 50 |
| 3 | Badges square → progressText | `1×2` | `game` | 40 (sub) |
| 4 | Care team square → "Call or message" | `1×2` | `calm` | 39 (sub) |
| 5 | Reminder strip "Keep your thermometer by the bed tonight" | `2×1` | `info` | 30 (sub) |

Greeting flips to **"Good evening, Elena"**; header level ring and clock update with the state.

## 3. Flow

```mermaid
sequenceDiagram
    participant U as User
    participant A as Agent (home planner)
    Note over A: evening → nextSample.tomorrow true
    A->>U: sample-prep card (2×3, hot) with 4-stop timeline
    A->>U: reminder strip (info) — thermometer by the bed
    U->>A: taps reminder strip
    A-->>U: toast "Reminder — I'll nudge you at the right time"
    Note over A: overnight; tomorrow the agent walks through each sample
```

Step by step:

1. Agent renders the sample-prep card: eyebrow (drop icon) `Tomorrow · booked by your care team`, headline **"Fingerstick samples · Sun 11 Oct"**.
2. Timeline with 4 stops: **Before dose → 1 h → 3 h → 6 h** (gradient line, violet nodes; first node cyan, last magenta).
3. Footnote: **"Fasting. I'll walk you through each one."** — sets the expectation that the agent guides step-by-step tomorrow, not tonight.
4. Reminder strip (`info`): "Keep your thermometer by the bed tonight" — tappable, toast confirms a nudge will come at the right time.
5. No questions tonight: the dose is already logged (done row only). The agent keeps the home calm.

## 4. Widget specs

- Card: `w compact`, tone `now`; eyebrow icon `i-drop`; headline names the test + date.
- Timeline `.tl`: 4 equal columns, nodes on a gradient rail; labels in Poppins 13 px.
- Reminder strip: `w row` with bell icon, `t1` "Reminder", `t2` reminder text, chevron.
- Done row: check disc + "Morning dose" + "Logged · late".

## 5. State mutations

| Field | Value |
|---|---|
| `daypart` | `"evening"` (drives greeting + which workflows can fire) |
| `nextSample.tomorrow` | `true` (set by care-team booking or date roll-over) |
| `reminders` | night-before prep reminders appended |
| No answers collected | nothing tonight increments check-ins or produces a flash |

## 6. Guardrails

- The sample was **booked by the care team** — the agent never re-books, reschedules, or edits the plan; it only narrates it.
- Fasting instruction comes from the care team's order; the agent repeats it verbatim, never improvises medical prep.
- The evening home must not carry over morning urgency: dose is a done row, not a `hot` tile.

## 7. CopilotKit mapping

**Shared agent state (`useCoAgent`)**: `daypart`, `nextSample`, `reminders`, `dose` (read-only here).

**Actions (`useCopilotAction`)**

| Action | Args | Render / effect |
|---|---|---|
| `render_sample_prep` | `when`, `stops: string[]`, `notes: string` | the `2×3 hot` timeline card |
| `set_reminder` | `text`, `fireAt` | info strip + toast on tap |
| `render_booked_row` | `when`, `test` | 1-row `high` strip for future (non-tomorrow) bookings |

**Generative-UI components**: `SamplePrepCard` (with `TimelineRail`), `ReminderStrip`, `DoneRow`.
