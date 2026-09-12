# Interactive Tour

Two self-contained pages anyone can open in a browser — no build step, no server, no local assets.
Each is a byte-identical copy of the v2 prototype it came from, kept here so the tour can be opened
directly without hunting through the plan folders.

| File | Source of record | What it shows |
|------|------------------|---------------|
| `clinic-board.html` | `plan-doctor-dashboard/prototype/doctor-dashboard-prototype-v2.html` | The clinician board: nine agent scenarios, the board-agent chat panel, and the retrieve bar. |
| `patient-widget.html` | `plan-phone-app/prototype/phone-app-prototype-v2.html` | The patient phone app: onboarding, consent, permissions, settings, lock screen, and eleven agent scenarios on the home. |

Both use the cream-and-green design. Typography is Poppins and Manrope, loaded from Google Fonts, so
the pages want a network connection to look right; they stay readable without one.

## Driving them

Each page has a demo panel down one side that switches the agent scenario — the drawer on the board,
the panel beside the phone. That panel is the demo driver, not part of the product, so hide it before
screenshotting anything: `body.demo-closed` on the board, `#demo` on the phone.

The phone routes by URL hash: `#/welcome`, `#/consent`, `#/access`, `#/permissions`, `#/now`,
`#/milestone`, `#/settings`, `#/lock`.

## Also published as live pages

The same two pages are published as private Claude artifacts, which is the easiest way to send them
to someone without them cloning anything:

- Clinic Board — https://claude.ai/code/artifact/8cc495cc-a61f-478f-9127-9628277a8e4f
- Patient Widget — https://claude.ai/code/artifact/6dcbc400-1d4f-496b-8c1e-223ce5869b57

Those two links are stable. Republishing updates them in place rather than making new ones.

## Keeping these in step

These copies do not update themselves. When either prototype changes, re-copy it here and republish
the matching artifact, or the tour and the prototype drift apart.
