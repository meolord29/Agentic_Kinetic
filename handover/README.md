# Agentic Kinetic — build handover

Everything needed to build the **patient app** and the **Clinic Board** for the Agents, Everywhere demo.
The backend is built and tested; the design is final; this folder is the build kit.

## Start here

1. **Give `AGENTS.md` to your coding assistant.** It is the complete contract: rules, API, every action end to
   end, screen copy, tokens, motion, and the tests to write.
2. **Open the three HTML files in a browser** (clone the repo and open them locally — GitHub shows HTML as source):
   - `deck-v2/ux/build-reference.html` — the same contract for people, with the agent diagram and full payloads.
   - `deck-v2/ux/screens/patient-widget-final.html` — the patient app, six screens, every option on a switch.
   - `deck-v2/ux/screens/clinic-board-final.html` — the Clinic Board, three frames, every option on a switch.
3. **Run the backend** (`agent-pk/`) and build against `deck-v2/ux/data/backend-capture.json` first.

## What is in this folder

| Path | What it is |
|---|---|
| `AGENTS.md` | Build contract for a coding assistant |
| `deck-v2/ux/build-reference.html` | Human-readable build reference |
| `deck-v2/ux/screens/patient-widget-final.html` | Patient app visual reference |
| `deck-v2/ux/screens/clinic-board-final.html` | Clinic Board visual reference |
| `deck-v2/ux/data/backend-capture.json` | Real responses from the backend for the synthetic patient |
| `agent-pk/src/agent_pk/` | The backend: PK model, deterministic gate, LangGraph agent with the human pause, FastAPI routes |
| `agent-pk/tests/` | The backend test suite |
| `agent-pk/data/` | The synthetic demo patient and the curated interaction data |
| `agent-pk/pyproject.toml`, `pytest.ini` | Pinned dependencies and test config |
| `agent-pk/handover/ARCHITECTURE.md` | Stack, pins, the two-channel rule, the pause, and what is built |
| `agent-pk/handover/PATIENT-REPORTED-DATA.md` | The check-in fields and why they are not a food diary |
| `agent-pk/docs/GUARDRAILS.md` | The regulatory mapping behind the rules |
| `agent-pk/docs/MODEL-CARD.md`, `TECH-STACK.md` | Model card and stack notes |
| `care-plan-schema/` | The clinician-authored care plan contract, with worked examples |

## Run the backend

```bash
cd agent-pk
python3.11 -m venv .venv && . .venv/bin/activate
pip install -e ".[api]"
python -m pytest tests/ -q                       # about 12 minutes; -m "not slow" while iterating
python -m uvicorn agent_pk.api.app:app --reload  # http://127.0.0.1:8000/api/health
```

## Scope

- **Build:** the Clinic Board decision flow, review and approval cards; the patient app check-in, thanks, badges,
  voice confirmation, booked samples and health-question handoff; Feedback motion.
- **Future development — do not build now:** the mood module and Motion graphics. Both are on the boards,
  labelled, so the direction is visible.
- **Data:** synthetic only. There is no patient data anywhere in this folder, and the backend has no network
  calls, keys or secrets.
