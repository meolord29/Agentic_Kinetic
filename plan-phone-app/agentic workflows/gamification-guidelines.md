# Agentic UI — Gamification guidelines

> Applies to **every widget the agent generates**, in every workflow (see the `workflow-0*.md` files in this folder). Source of truth: `prototype/phone-app-prototype-v2.html` — copy its exact visual language, do not invent new chrome.

The agent owns the home stack. Whatever it renders mid-flow — a new question card, a nudge, a progress tile, a celebration — must obey the rules below so the app stays warm, motivating, and trustworthy.

---

## 1. The core loop (never break it)

```
honest check-in → micro-reward → visible progress → next goal
```

1. **Check-in** — one question, one tap (workflow-01 is the only check-in that counts: dose answers increment `checkins`).
2. **Micro-reward** — immediate thank-you flash card (`good` tone): "Thanks for telling us! Your care team now has the full picture." + `+1 check-in` pill for dose check-ins.
3. **Visible progress** — header level ring (`--p` conic gradient, L = `floor(checkins/25)+1`) + progress text ("3 more check-ins to First month").
4. **Next goal** — badges square (`game` tone) always shows the distance to the *next* badge: 1 / 7 / 30 / 100 / 365.

Every new widget the agent generates must slot into this loop or explicitly stay out of its way (care-logistics widgets never fake rewards).

## 2. Mandatory vocabulary for any generated widget

**Sizing grid** — 2-column bento, 82 px row units:

| Spec | Meaning | Use for |
|---|---|---|
| `2×N` full-width | spans both columns | the one thing being asked right now |
| `1×N` half-width | one column | secondary/ambient tiles (badges, care team, temperature) |
| 1-row strip | thin full-width row | booked events, reminders, done records |
| `2×5` | full-width, tall | **celebrations only** |

**Tone = importance, never decoration.** A generated widget must declare exactly one:

| Tone | Class | Meaning |
|---|---|---|
| `hot` | `.now` | due right now — gradient border, top of stack |
| `high` | `.t-high` | today's care logistics (booked, handoff) |
| `info` | `.t-info` | reminders, FYI |
| `game` | `.t-game` | progress, badges, streaks |
| `good` | `.t-good` | thanks / just-completed |
| `calm` | — | resting, all-clear |
| `done` | `.done` | collapsed record of an answered item |

**Stack rules**: done rows first → main tiles by priority → sub tiles. One question at a time: only the highest-priority `hot` tile may ask something. Every answer triggers a full re-plan.

## 3. Reward rules for agent-generated widgets

1. **Check-ins are sacred.** Only dose check-ins earn `+1` / badge credit. Never award check-ins, points, or badges for temperature logs, symptom notes, team-question answers, or handoffs.
2. **Badges reward honesty, not adherence.** Thresholds are exact: 1, 7, 30, 100, 365 check-ins. "Missed it" at #30 still unlocks. Never gate any reward on a "good" answer.
3. **One celebration at a time.** A badge unlock renders as a single `2×5 hot` card at the top (weight 99) and suppresses the flash card until "Keep going". Never stack two reward moments, never queue celebrations.
4. **Celebrations interrupt; everything else doesn't.** Only `unlock` may jump the stack. New widgets otherwise animate in place (staggered `agent-in`, 45 ms).
5. **Game widgets must carry live progress.** Any `game`-tone tile shows real state: the level ring percentage, or progressText ("19 more check-ins to First month"). If all badges are earned: "Every check-in counts".
6. **Locked ≠ hidden.** Unearned badges on shelves/screens render grayscale + dimmed, with label and number visible. Never invent badges, never retroactively change thresholds, never reset or lose progress.
7. **No dark patterns.** No streak-shaming, no countdowns, no loss-aversion, no penalties for missed doses, no red on answers. Copy for any answer is identical in warmth.

## 4. Copy rules (applies to every generated string)

- Non-judgmental, plain, short. Headlines ≤ 6 words where possible.
- The reassurance line "Every answer counts the same." belongs on question cards with judgmental-looking options (Took it / Missed it / Not sure).
- Thank-you copy is fixed: "Thanks for telling us!" / "Your care team now has the full picture." Don't paraphrase per-widget.
- Progress copy format: "{d} more check-in{s} to {badge label}".
- Never imply the agent is a clinician; care-team content is labelled as theirs ("Your care team asks", "Booked by your care team").
- No exclamation-mark stacking, no "Amazing!! 🎉" — the joy comes from motion and color, not from hyped copy.

## 5. Motion & feel

- Tiles enter with `agent-in` (fade + 8 px rise), staggered 45 ms per tile.
- Reward moments animate: badge `pop` (scale .55→1.06→1) and two `ringpulse` rings (staggered 0.5 s); level ring animates `--p` over 0.9 s.
- Toasts confirm non-blocking actions ("Booked by your care team — I'll walk you through it the evening before").
- **All celebration/entry motion collapses to static under `prefers-reduced-motion: reduce`.** State changes must remain legible without animation.

## 6. Priority: care outranks game, always

- Weight order is fixed: celebration (99) > flash (90) > live care questions (80–72) > handoff (70) > done rows > sub tiles (game 40, calm 39, reminder 30, booked 50).
- A generated widget may **never** insert itself above a live care question. If a new gamified widget is warranted mid-flow, it enters as a sub tile (`game` tone) and waits its turn.
- On sick days (workflow-08): rewards stay quiet — thanks flash only, no +1, no celebrations, no game nags.

## 7. Anti-patterns (agent must never)

| Anti-pattern | Why |
|---|---|
| Points/star economy beyond check-ins | dilutes the one honest metric the care team relies on |
| Red badges / alarms for missed doses | shame kills disclosure; the data matters more than adherence |
| Streaks that break | loss aversion punishes honesty — use cumulative badges instead |
| Celebration stacking / reward spam | one moment, fully felt, beats three missed ones |
| Gamified handoffs ("+5 for calling your team!") | care logistics are not a game |
| Hiding unearned badges | visible goals drive the loop; grayscale keeps hope, locked opacity hides it |
| Filler widgets when idle | nothing due → the calm all-clear card only (workflow-09) |
| New chrome, new colors, new fonts | reuse the tokens: `--cyan/--violet/--magenta` gradient, sand `game` tint, Poppins/Manrope |

## 8. Quick checklist for any generated widget

- [ ] Declares one tone from the table and the correct size from the grid
- [ ] Asks at most one question (and only if it's the top `hot` tile)
- [ ] Rewards only dose check-ins; badges only at exact thresholds
- [ ] Shows real progress (ring %, progressText) — never fake numbers
- [ ] Identical chip sizing + non-judgmental copy for all answers
- [ ] One celebration max, dismissed via "Keep going"
- [ ] Uses only existing tokens/typography; staggered entry ≤ 45 ms; reduced-motion fallback
- [ ] Never outranks a live care task; never fabricates a task when state is clear
