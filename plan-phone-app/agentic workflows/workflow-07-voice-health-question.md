# Workflow 07 — Voice · health question handoff

> Source: demo scenario `data-sc="health"` → voice popover result (`voice.type = "health"`) → handoff card, weight **70**, layout `{cols:2, rows:3, tone:'high'}` in `prototype/phone-app-prototype-v2.html`.

| | |
|---|---|
| **Trigger** | User holds the mic FAB ("Hold to talk"); the transcript is a **clinical/health question** — e.g. "Can I take ibuprofen for my back?" |
| **Agent intent** | Confirm what was heard, then **hand the question to the human care team**. The agent must never answer it. |
| **Entry points** | Hold-to-talk FAB (home or milestone screen). |
| **Exit / handoff** | Handoff card stays pinned (`high` tone) until the care team replies here; ghost button offers a phone call. |

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
- **The agent never answers clinical questions — it hands off to the care team.** This workflow is that handoff.
- The agent never invents care tasks. Nothing due → calm resting card only.
- New tiles animate in staggered (`agent-in`, 45 ms per tile). Respect `prefers-reduced-motion`.

---

## 1. Preconditions (agent knowledge)

```json
{
  "checkins": 31,
  "dose": { "status": "done", "answer": "taken" },
  "voice": { "type": "health", "said": "Can I take ibuprofen for my back?" },
  "handoff": null,
  "teamQuestion": null, "temp": { "due": false, "status": "none" },
  "newMed": null, "symptoms": [], "vomit": null,
  "nextSample": { "booked": false, "when": "Sun 11 Oct", "tomorrow": false },
  "reminders": [], "flash": null, "unlock": null
}
```

## 2. Stage plan

**Stage A — voice popover** (floating card over the FAB, `listen-pop`, 300 px, bottom-right):

| State | Contents |
|---|---|
| Listening | eyebrow (mic) `Listening` · animated wave bars (gradient) · **Release to send** · "Only the words are kept. The voice itself is never analysed." |
| Result | eyebrow `You said` · the transcript in quotes · **Looks right** (primary) · **Say it again** (ghost → back to listening) |

**Stage B — home stack** (after confirm):

| Priority | Widget | Layout | Tone | Weight |
|---|---|---|---|---|
| 1 | Handoff card ("You asked") | `2×3` | `high` | 70 |
| 2 | Badges square → progressText | `1×2` | `game` | 40 (sub) |
| 3 | Care team square → "Call or message" | `1×2` | `calm` | 39 (sub) |

## 3. Flow

```mermaid
sequenceDiagram
    participant U as User
    participant A as Agent
    U->>A: holds FAB, speaks "Can I take ibuprofen for my back?"
    A->>U: listening pop (wave, release to send)
    A->>A: classify transcript → health question
    A->>U: result pop — "You said" + Looks right / Say it again
    U->>A: Looks right
    A->>A: handoff = { q: said }; close pop; route home
    A->>U: handoff card 2×3 high + receipt "Question sent to your care team · just now"
```

Step by step:

1. Hold FAB → listening popover: wave animation, "Release to send", privacy line.
2. Release → transcript is classified. A question aimed at clinicians ("can I take…", "should I…") routes to **this** workflow, never to an answer engine.
3. Result popover shows the transcript verbatim under "You said" with **Looks right** / **Say it again**. No commit before confirmation.
4. Confirm → popover closes, agent routes to home, sets `handoff = { q }`.
5. Handoff card renders:
   - Eyebrow: **You asked**.
   - The user's words as a pull-quote: “Can I take ibuprofen for my back?”
   - Team line (icon + text): "That's one for your care team. I've sent your question to them and they'll reply here."
   - Ghost button: **Call your care team** → toast "Demo — no call placed".
   - Receipt strip (check icon): "Question sent to your care team · just now" + tag `TO CARE TEAM`.
6. The card persists until a reply lands in its place; the agent does not summarize or paraphrase the question out of existence.

## 4. Widget specs

- Popover: `listen-pop`, radius 24, shadow; wave = 24 gradient bars of varying height; result rows use `.rows` label/value/Change pattern when facts are noted (not used in this type).
- Handoff card: `w compact` `t-high`; pull-quote uses `.say` (ink, 17 px); receipt `.rcpt` with gradient-check icon and uppercase em tag.

## 5. State mutations

| Field | After |
|---|---|
| `voice` | `{ type:"health", said }` — kept for the quote |
| `handoff` | `{ q: "<transcript>" }` — pinned until care-team reply |
| `flash` | **not set** — handoffs are logistics, not check-ins; no +1 |

## 6. Guardrails

- **Hard safety rule**: the agent never provides medication advice, dosing, or clinical interpretation. Classification confidence doesn't matter — when in doubt, it's a handoff.
- The question is relayed **verbatim**; the agent may not edit, soften, or "improve" what the user asked.
- Privacy line is always shown while listening: "Only the words are kept. The voice itself is never analysed."
- The user can always fall back to a human call (**Call your care team**).

## 7. CopilotKit mapping

**Shared agent state (`useCoAgent`)**: `voice`, `handoff`.

**Actions (`useCopilotAction`)**

| Action | Args | Render / effect |
|---|---|---|
| `classify_voice_note` | `transcript` | returns `type: "dose" \| "health" \| "sick"` → routes workflow |
| `render_voice_result` | `type:"health"`, `said` | result popover with confirm/re-record |
| `confirm_voice_note` | — | commit path ("Looks right") |
| `send_question_to_care_team` | `q` | sets `handoff`, renders receipt |
| `call_care_team` | — | toast "Demo — no call placed" (real build: dialer) |

**Generative-UI components**: `VoiceListeningPop`, `VoiceResultPop`, `HandoffCard`, `ReceiptStrip`.
