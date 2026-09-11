"""graph.py — the LangGraph wiring. Owns the pause; owns no clinical decision.

Deliberately thin, and deliberately separate from `evaluate.py`, for the same reason
`interactions/langgraph_tool.py` is separate from `interactions/tool.py`: the decisions are the
reviewable part and they must be testable with no graph runtime installed. Everything here is
sequencing.

WHY THE PAUSE IS A GRAPH INTERRUPT AND NOT AN AGENT-INITIATED TOOL CALL. The escalation decision
is made by `Prediction.crosses_boundary` in deterministic Python, and the whole regulatory
argument rests on that (`docs/GUARDRAILS.md`). A CopilotKit `useHumanInTheLoop` pause is
*agent-initiated* — the model chooses whether to raise the offer — which would move the gate
inside the model. `interrupt()` is *graph-enforced*: the node reaches it only because the gate
already fired, and the run cannot continue past it until a person answers. The frontend may
render that offer however it likes; it cannot decide whether the offer exists.

That also makes the fallback and the preferred route the same code. A clinician answering
through a plain HTTP route and a clinician answering through a generative-UI card both resume
the same interrupt, so the interaction survives a frontend that turns out not to support the
primitive we wanted.

The graph is imported explicitly, never from the package `__init__`, so `agent_pk` stays
importable in an environment holding the numeric core and no agent stack:

    from agent_pk.agent.graph import build_graph
"""

from __future__ import annotations

import logging
from typing import Any, Final, Literal, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agent_pk.agent.case import PatientCase, ReviewRequired
from agent_pk.agent.evaluate import (
    appointment_for,
    build_clinician_view,
    evidence_notes,
    exposure_for,
    fit_case,
    gate_action,
    offer_for,
    predict_case,
)
from agent_pk.channel import ClinicalAction, ClinicianView, SampleAppointment
from agent_pk.pk.calibration import ExposureEstimate, SamplingOffer
from agent_pk.pk.fit import FitResult, Prediction
from agent_pk.pk.model import PkInputError
from agent_pk.pk.priors import PopulationPrior

logger = logging.getLogger(__name__)

#: The only two answers a clinician may give to a sampling offer. A third value is a defect in
#: the caller, not a new clinical option, so it raises rather than falling through to a default
#: — and the default it would fall through to is "declined", which suppresses an escalation.
ACCEPTED: Final[str] = "accepted"
DECLINED: Final[str] = "declined"

#: `route_after_predict` returns the literal `"__end__"` so its declared `Literal` return type
#: keeps constraining it. This asserts that literal is still what LangGraph means by `END`.
if END != "__end__":  # pragma: no cover - a LangGraph change, not a runtime condition
    raise AssertionError(
        f"langgraph END is {END!r}, not '__end__'; routing would misfire"
    )


class PkAgentState(TypedDict, total=False):
    """One evaluation's state as it moves through the graph.

    `total=False` because most keys are produced by a node rather than supplied: only `case` is
    an input. Every other key is absent until the node that owns it has run, and absent is
    meaningfully different from empty at every one of them.

    `run_complete` IS THE ONE KEY A READER OUTSIDE THE GRAPH MAY TRUST, and it exists because a
    checkpointed thread that is re-run KEEPS the previous run's keys: LangGraph merges each
    node's update into the stored state and never clears what no node rewrote. So the ABSENCE of
    `clinician_view` cannot mean "not decided yet" — after one completed run it is present
    forever, and a reader branching on `is None` reads a SUPERSEDED decision as the current one.
    Measured: evaluate, accept, then evaluate again, and the patient route served
    `SAMPLE_SCHEDULED` with a booked appointment while the clinician sat at a fresh unanswered
    offer. `fit_node` therefore CLEARS the whole per-run outcome set at the start of every run
    and sets this False; `view_node` sets it True. A positive assertion of completeness, not an
    absence check — found by the Stage-A verifier on the integration scope.
    """

    case: PatientCase
    prior: PopulationPrior
    fit: FitResult
    prediction: Prediction | None
    review_required: ReviewRequired | None
    action: ClinicalAction | None
    offer: SamplingOffer | None
    offer_unavailable_reason: str
    decision: str
    appointment: SampleAppointment | None
    exposure: ExposureEstimate | None
    clinician_view: ClinicianView | None
    run_complete: bool


#: The keys a RUN produces. Every one of them is cleared by `fit_node` at the start of the next
#: run, and `_check_clear_is_complete()` below makes that a checked fact rather than a habit.
#:
#: THIS EXISTS BECAUSE THE FIRST VERSION OF THE CLEAR WAS INCOMPLETE. It cleared six keys and left
#: `offer`, `prediction`, `action` and `exposure` standing, so a thread that ran a crossing case
#: and then an in-range one ended with the new view beside the OLD offer and the OLD predicted
#: interval. Found by a decorrelated verifier, which observed that the fix had the same shape as
#: the bug it closed: a hand-maintained list of keys to remember. So the list is no longer
#: hand-maintained against memory — it is derived from the state's own annotations and checked.
_RUN_INPUT_KEYS: Final[frozenset[str]] = frozenset(
    {"case", "prior", "fit", "run_complete"}
)
PER_RUN_OUTCOME_KEYS: Final[frozenset[str]] = (
    frozenset(PkAgentState.__annotations__) - _RUN_INPUT_KEYS
)

#: What each outcome key is cleared TO. Not all of them are None: two are strings whose "absent"
#: value is empty, and conflating the two would put `None` where a `str` is declared.
_CLEARED_STATE: Final[dict[str, object]] = {
    "prediction": None,
    "review_required": None,
    "action": None,
    "offer": None,
    "offer_unavailable_reason": "",
    "decision": "",
    "appointment": None,
    "exposure": None,
    "clinician_view": None,
}


def _check_clear_is_complete() -> None:
    """Fail at import if a state key exists that no run clears.

    Adding a key to `PkAgentState` without adding it here is exactly how the first clear came to
    be incomplete, and the consequence is a superseded value read as current. Making it a startup
    failure means the omission cannot be shipped.

    Raises:
        AssertionError: If the cleared set and the outcome set disagree in either direction.
    """
    cleared = frozenset(_CLEARED_STATE)
    if cleared != PER_RUN_OUTCOME_KEYS:
        raise AssertionError(
            "every per-run state key must be cleared at the start of the next run; "
            f"not cleared: {sorted(PER_RUN_OUTCOME_KEYS - cleared)!r}; "
            f"cleared but not a run outcome: {sorted(cleared - PER_RUN_OUTCOME_KEYS)!r}"
        )


_check_clear_is_complete()


# ── Nodes ────────────────────────────────────────────────────────────────────


def fit_node(state: PkAgentState) -> PkAgentState:
    """Build the prior and fit this patient against it."""
    prior, fit = fit_case(state["case"])
    # CLEAR THE PREVIOUS RUN'S OUTCOMES. See `PkAgentState.run_complete`: a re-run inherits every
    # key no node overwrites, so an outcome left standing here is read by the patient route as
    # this run's decision. Cleared at the START, so the window in which a stale value is
    # readable does not exist rather than being merely short.
    update: PkAgentState = {"prior": prior, "fit": fit, "run_complete": False}
    update.update(_CLEARED_STATE)  # type: ignore[typeddict-item]
    return update


def predict_node(state: PkAgentState) -> PkAgentState:
    """Predict the target trough, or record that it could not be predicted."""
    outcome = predict_case(state["case"], state["fit"])
    if isinstance(outcome, ReviewRequired):
        return {"review_required": outcome}
    return {"prediction": outcome}


def gate_node(state: PkAgentState) -> PkAgentState:
    """Apply the deterministic escalation gate. The decision itself lives in `evaluate`."""
    prediction = state["prediction"]
    if prediction is None:
        raise PkInputError("gate_node reached with no prediction to gate")
    return {"action": gate_action(prediction)}


def offer_node(state: PkAgentState) -> PkAgentState:
    """Build the sampling offer and STOP until a person answers it.

    Reached only when the gate has already fired, so the offer's existence is never a model's
    choice. `interrupt` suspends the run here; the answer arrives on a resume.

    Raises:
        PkInputError: If the resumed answer is neither ACCEPTED nor DECLINED. A default would
            be `declined`, which silently suppresses the escalation this node exists to raise.
    """
    case = state["case"]
    outcome = offer_for(case, state["fit"], state["prior"])
    if isinstance(outcome, str):
        # The forecast failed; the CROSSING STILL STANDS, so this degrades to a review flag
        # rather than to no action, and there is nothing to ask a clinician to accept.
        return {
            "offer_unavailable_reason": outcome,
            "action": ClinicalAction.FLAG_FOR_REVIEW,
        }

    answer = interrupt(sampling_offer_payload(case, state["fit"], outcome))
    decision = answer.get("decision") if isinstance(answer, dict) else answer
    if decision not in (ACCEPTED, DECLINED):
        raise PkInputError(
            f"a sampling offer may only be {ACCEPTED!r} or {DECLINED!r}, got {decision!r}"
        )
    if decision == DECLINED:
        return {
            "offer": outcome,
            "decision": DECLINED,
            "action": ClinicalAction.FLAG_FOR_REVIEW,
        }
    return {
        "offer": outcome,
        "decision": ACCEPTED,
        "appointment": appointment_for(case, outcome),
        "action": ClinicalAction.SCHEDULE_ADDITIONAL_PK_SAMPLE,
    }


def view_node(state: PkAgentState) -> PkAgentState:
    """Assemble the clinician view. Raises rather than serving an incomplete basis.

    `exposure` is written UNCONDITIONALLY, including when it is None. Writing it only when it
    could be computed leaves a previous run's estimate standing beside a view built without one —
    the same superseded-value defect as the incomplete clear, in the one key that had a
    conditional write. Found by a decorrelated verifier.
    """
    case = state["case"]
    fit = state["fit"]
    prediction = state["prediction"]
    action = state["action"]
    if prediction is None or action is None:
        # Unreachable: `route_after_predict` ends the run without a prediction, and every path
        # into this node passes through `gate_node`. Loud rather than a TypeError, because the
        # thing that would otherwise happen here is a half-built view.
        raise PkInputError(
            "view_node reached without a prediction or an action; nothing can be reported "
            "about this patient and it must not be presented as an ordinary result"
        )
    exposure = exposure_for(case, fit)
    view = build_clinician_view(
        case,
        fit,
        prediction,
        action,
        state.get("appointment"),
        exposure,
    )
    return {"clinician_view": view, "run_complete": True, "exposure": exposure}


# ── Routing ──────────────────────────────────────────────────────────────────


def route_after_predict(state: PkAgentState) -> Literal["gate", "__end__"]:
    """End the run when there is no prediction to gate.

    A degenerate sample is NOT routed on to the gate with a missing prediction — the gate would
    have nothing to read, and whatever it returned would be a verdict nobody computed.

    Tests `is not None` rather than key PRESENCE: `fit_node` now clears the key to None at the
    start of every run, so on a re-run the key is present-and-None and a membership test would
    end the run on the PREVIOUS run's failure.
    """
    # The literal rather than `END`, which LangGraph types as a bare `str` — returning it
    # widens this function's return type and the Literal above stops constraining anything.
    # Asserted equal at import so the two can never drift.
    return "__end__" if state.get("review_required") is not None else "gate"


def route_after_gate(state: PkAgentState) -> Literal["offer", "view"]:
    """Send a crossing to the offer, and everything else straight to the view."""
    action = state["action"]
    if action is None:
        raise PkInputError("route_after_gate reached before the gate set an action")
    if action is ClinicalAction.NO_ACTION:
        return "view"
    return "offer"


# ── The offer payload the frontend renders ───────────────────────────────────


def sampling_offer_payload(
    case: PatientCase, fit: FitResult, offer: SamplingOffer
) -> dict[str, Any]:
    """The JSON the clinician is asked to accept or decline.

    LEADS WITH THE EXPOSURE WIDTH, NOT THE CALIBRATION SCORE, and carries the burden beside the
    gain. Calibration rises in the forecast and falls once real post-dose points land, because a
    three-parameter fit carries absorption uncertainty a trough-only fit assumes away — a card
    built on it promises an improvement and delivers a drop. The calibration figures travel as
    a clearly-named secondary block so a renderer that wants them has them, and a renderer
    following this docstring does not lead with them.

    Args:
        case: The evaluation's inputs, for the times and the citations.
        fit: The fit the offer was scored against. Passed in rather than recomputed, so the
            citations on the card cannot describe a different fit from the one the decision
            was made on.
        offer: The scored offer.

    Returns:
        A plain JSON-serialisable dict. No domain objects cross this boundary.
    """
    return {
        "kind": "sampling_offer",
        "question": (
            "This patient's predicted trough interval reaches a boundary of their care plan, "
            "and the current estimate cannot be independently checked. Take extra samples?"
        ),
        "next_dose_time_h": case.next_dose_time_h,
        "offsets_post_dose_h": list(offer.offsets_post_dose_h),
        "fasted_required": True,
        "burden": {
            "extra_draws": offer.n_extra_samples,
            "note": (
                "Draws beyond the trough already scheduled. This is what the patient "
                "actually experiences as extra."
            ),
        },
        "expected_gain": {
            "exposure_width_now": offer.exposure_width_now,
            "expected_exposure_width": offer.expected_exposure_width,
            "exposure_width_gain": offer.exposure_width_gain,
            "independently_checkable_now": offer.independently_checkable_now,
            "expected_independently_checkable": (
                offer.expected_independently_checkable
            ),
        },
        "secondary_parameter_precision": {
            "note": (
                "Parameter precision, NOT accuracy. It scores a trough-only fit higher than a "
                "curve fit because the trough-only fit assumes absorption away. Do not lead a "
                "clinician-facing card with these."
            ),
            "calibration_now": offer.calibration_now,
            "expected_calibration": offer.expected_calibration,
        },
        "evidence": [
            {
                "claim": note.claim,
                "source_url": note.source_url,
                "population_limit": note.population_limit,
            }
            for note in evidence_notes(case, fit)
        ],
        "answers": [ACCEPTED, DECLINED],
    }


# ── Assembly ─────────────────────────────────────────────────────────────────


def build_graph(checkpointer: InMemorySaver | None = None) -> Any:
    """Compile the evaluation graph.

    Args:
        checkpointer: Where interrupted runs are held between the offer and its answer. An
            `InMemorySaver` is created when none is given, which is correct for a
            demonstration and is NOT durable — a restart loses every pending offer. A
            deployment supplies a durable checkpointer here.

    Returns:
        The compiled graph. `invoke` returns the final state, or a state carrying `__interrupt__`
        when it is waiting on a sampling decision.
    """
    builder = StateGraph(PkAgentState)
    builder.add_node("fit", fit_node)
    builder.add_node("predict", predict_node)
    builder.add_node("gate", gate_node)
    builder.add_node("offer", offer_node)
    builder.add_node("view", view_node)

    builder.add_edge(START, "fit")
    builder.add_edge("fit", "predict")
    builder.add_conditional_edges("predict", route_after_predict)
    builder.add_conditional_edges("gate", route_after_gate)
    builder.add_edge("offer", "view")
    builder.add_edge("view", END)

    return builder.compile(checkpointer=checkpointer or InMemorySaver())
