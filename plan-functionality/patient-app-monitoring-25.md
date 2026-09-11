# The 25 most important things the patient phone app should have, from a healthcare stance

Grounded in the `handover/` build kit (AGENTS.md contract, ARCHITECTURE.md, GUARDRAILS.md,
PATIENT-REPORTED-DATA.md, MODEL-CARD.md, care-plan-schema with the transplant-tacrolimus
example, and the patient-widget/build-reference HTML). One agent, two surfaces: the backend
computes for the clinician; the patient app is a **projection** — it displays her own data
and her clinician's own words, and interprets nothing (`agent-pk/docs/GUARDRAILS.md`).

Context: kidney-transplant tacrolimus monitoring between monthly blood draws. Non-adherence
carries roughly seven times the graft-loss risk, and the first silent warning arrives years
before failure — the app's job is to make the patient's everyday reality visible to the care
team in time, without ever becoming a medical device function in her hands
(`care-plan-schema/examples/transplant-tacrolimus.plan.json`, `GUARDRAILS.md`).

---

## A. Clinical safety and regulatory boundaries

1. **Daily dose check-in with four non-judgemental answers** ("Took it" / "Took it late" /
   "Missed it" / "Not sure") — adherence is the single largest modifiable graft-loss risk, and
   an honest "Missed it" is worth more than a flattering silence. `AGENTS.md §5D`
2. **Never show an interpretation** — no drug level, prediction, interval, in/out-of-range
   verdict, direction of travel, dose advice, or interaction verdict in the patient channel;
   enforced structurally in Python, not by hiding fields. `AGENTS.md §3.1–3.3`, `ARCHITECTURE.md`
3. **Health questions are never answered** — any health/medicine question becomes a handoff
   widget routed to the care team; the app never practices medicine. `AGENTS.md §5G`, `GUARDRAILS.md §6`
4. **Instructions reach the patient only in her clinician's own words** — plan text verbatim,
   questions only after clinician Send/Edit approval; unapproved drafts never render.
   `AGENTS.md §3.6, §5F`
5. **Always-visible human contact path and AI disclosure** — "Call your care team" in the menu
   on every screen plus "This app uses AI" (AB 489 / AB 3030 / TRAIGA physician-review design).
   `AGENTS.md §6`, `GUARDRAILS.md §6`
6. **A closed, true-only message vocabulary** — `nothing_to_do` / `sample_scheduled` /
   `contact_your_team` / `evaluation_may_be_helpful`; a message is served only if true of the
   system as built (e.g. `clinician_notified` is refused until a channel exists). `ARCHITECTURE.md`

## B. Monitoring capture

7. **Sample-validity annotations, not a food diary** — `food_within_window`,
   `minutes_dose_to_nearest_meal`, `meal_size_vs_usual`, `typical_day`; fed vs fasted moves
   Tmax ~4.7×, so these five fields decide whether a blood sample is interpretable.
   `agent-pk/handover/PATIENT-REPORTED-DATA.md §3`
8. **Hold-to-talk voice with patient-verified extraction** — transcript only, model extracts
   only the typed fields, she confirms with "Looks right" / "Change"; her words, her sign-off,
   no voice analysis. `AGENTS.md §5E`
9. **New-medicine watch via approved question** — "Did you start any new medicine this week?";
   interacting drugs (CYP3A4 inhibitors/inducers, NSAIDs) are the classic silent threat a
   non-transplant prescriber misses. `AGENTS.md §5F`, root `README.md` trigger events
10. **Vomited-after-dose event capture** — a dose vomited within the hour is effectively a
    missed dose with a different clinical meaning; on-event, stale after 24 h.
    `care-plan-schema/examples/transplant-tacrolimus.plan.json`
11. **Daily temperature capture, fixed time, same thermometer** — fever ≥38 °C is a
    same-day infection signal in an immunosuppressed patient. `transplant-tacrolimus.plan.json`
12. **Missed-dose pattern tracking (7-day count, consecutive misses)** — patterns, not single
    events, drive escalation (≥2 missed in 7 days → coordinator today); surfaced to the care
    team, never scored at the patient. `transplant-tacrolimus.plan.json` derived metrics

## C. Sample and appointment loop

13. **Fingerstick booking widget with fasting + offsets timeline** ("Before dose · 1 h · 3 h ·
    6 h") — the sampling protocol only means something if she can follow it; evening before,
    it takes over as the big widget. `AGENTS.md §5C, §6.5`
14. **A proposal never renders as booked** — `next_sample` is null until a clinician actually
    accepts; a declined offer must not appear on her phone as an appointment. `ARCHITECTURE.md`
15. **Silence is a state** — an unanswered check-in goes stale (`missing_after_hours`) and can
    escalate; no answer never reads as "normal", and escalation ladders climb until a human
    acknowledges. `care-plan-schema/README.md`, `transplant-tacrolimus.plan.json`
16. **Every answer logged with timestamp to the care team** — "Your care team now has the full
    picture" must be literally true of the system, or the thanks is a lie. `AGENTS.md §5D`

## D. Engagement that protects data quality

17. **Identical thanks and +1 for all four answers** — no streaks, leaderboards, on-time
    bonuses, or sad reaction to "Missed it"; any reward for the "right" answer buys flattering
    data and loses true data. `AGENTS.md §3.7`
18. **Milestone badges and levels where every answer counts** (1, 7, 30, 100, 365; level every
    25) — twenty-year adherence journey, reinforcement for reporting rather than for complying.
    `AGENTS.md §6`
19. **Widgets, not a chat** — what is due now is one big widget, done items shrink; a check-in
    completes in seconds, which is what keeps a chronic patient answering in year three.
    `AGENTS.md §1`, root `README.md` habit-loop notes
20. **Contextual timing of prompts** — the check-in anchors to her actual dose routine and the
    booking appears the evening before; nudges that follow her rhythm prevent alarm fatigue.
    `handover/README.md`, root `README.md` predictive notification notes

## E. Access, equity and usability

21. **Accessibility baseline** — contrast ≥4.5:1, touch targets ≥48px (talk button 66px), text
    to 200% without clipping, reduce-motion support, colour never the only signal. `AGENTS.md §9`
22. **Theme follows the device with a manual switch; bilingual prompts** — the care plan carries
    en + zh-Hant patient-facing questions; language and theme are access issues, not polish.
    `transplant-tacrolimus.plan.json`, `AGENTS.md §8`
23. **Low-friction and redundant input paths** — lock-screen micro-check-in under ten seconds,
    "Type instead" always one tap behind voice; if logging is effortful, the sickest days are
    the ones that go unrecorded. root `README.md` frictionless micro-logging, `AGENTS.md §6.4`

## F. Data protection and trust

24. **Consent with separated scopes, tested at the moment of use** — own care / de-identified
    improvement / identified research (refused outright); revocation recorded, exclusions carried
    never dropped. `GUARDRAILS.md §5`, `agent_pk/compliance/`
25. **De-identification before any training, and audit-every-access** — minimum necessary is
    enforced at the API layer (a read returns only the fields it declared and logs them);
    the training path never sees identifiable data. `GUARDRAILS.md §5`, `MODEL-CARD.md`

---

**Out of scope by contract:** the mood / "Hard days" module and Motion graphics are on the
boards labelled FUTURE DEVELOPMENT and must not be built now (`handover/README.md` Scope).

**Disclaimer:** Agent PK is a research prototype built for a hackathon — not a medical device,
not cleared or approved by any regulator, and it must not be used to make any decision about
the care of a real patient. If you are a transplant patient, talk to your transplant team.
(`agent-pk/docs/GUARDRAILS.md §9`)
