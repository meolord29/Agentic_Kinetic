"""The agent layer: what one evaluation is, and what it decides.

This package's `__init__` exports only the FRAMEWORK-FREE half — the typed case, the two
outcomes, and the deterministic evaluation steps. `graph.py` (LangGraph) and the API package
(FastAPI) are imported explicitly by whoever needs them, so `agent_pk` stays importable in an
environment holding the numeric core and no agent stack. That is the same guard, for the same
reason, as `interactions.langgraph_tool` being absent from its package `__init__`:

    from agent_pk.agent.graph import build_graph      # needs langgraph
    from agent_pk.api.app import app                  # needs fastapi
"""

from agent_pk.agent.case import CarePlan, PatientCase, ReviewRequired
from agent_pk.agent.evaluate import (
    appointment_for,
    attributions_for,
    build_clinician_view,
    calibration_note,
    evidence_notes,
    exposure_for,
    fit_case,
    gate_action,
    offer_for,
    parameter_estimates,
    predict_case,
)

__all__ = [
    "CarePlan",
    "PatientCase",
    "ReviewRequired",
    "appointment_for",
    "attributions_for",
    "build_clinician_view",
    "calibration_note",
    "evidence_notes",
    "exposure_for",
    "fit_case",
    "gate_action",
    "offer_for",
    "parameter_estimates",
    "predict_case",
]
