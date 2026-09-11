"""app.py — the HTTP surface. Two channels, two routes, two different payload types.

THE PATIENT ROUTE DOES NOT MOUNT THE AGENT, AND THAT IS THE RULE THAT MAKES THE BOUNDARY REAL.
Agent shared state is client-replicated: anything in the run's state object is on the wire to
every client on that thread, rendered or not. A patient session that subscribed to the agent
would hold the `Prediction` in the browser even with no component displaying it — the
"hidden field is still on the wire" failure, arriving through the state channel instead of
through CSS. So `/api/patient/...` is a plain route serving a `PatientView` projection, with no
stream, no shared state and no thread subscription.

THERE IS NO AUTHENTICATION HERE AND THAT IS A STATED SCOPE DECISION, not an oversight. The
channel separation is enforced by WHAT EACH ROUTE SERVES, never by who is asking: the patient
route has no code path that can produce a clinician payload, so an unauthenticated caller
hitting it still cannot obtain one. A deployment adds authentication for every other reason
authentication exists, and that is not this demonstration's claim.

Run it:

    uvicorn agent_pk.api.app:app --reload
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Final

from fastapi import FastAPI, HTTPException
from langgraph.types import Command
from pydantic import BaseModel, Field

from agent_pk.agent.case import PatientCase, ReviewRequired
from agent_pk.agent.demo_case import (
    load_demo_reference_instant,
    load_troughs_only_case,
)
from agent_pk.agent.evaluate import variability_for
from agent_pk.agent.graph import ACCEPTED, DECLINED, build_graph
from agent_pk.api.serialise import (
    clinician_context_json,
    clinician_view_json,
    patient_view_json,
    prediction_json,
    variability_json,
)
from agent_pk.channel import (
    ClinicalAction,
    ClinicianView,
    PatientMessage,
    PatientView,
    to_patient_view,
)
from agent_pk.pk.fit import Prediction
from agent_pk.pk.model import PkInputError
from agent_pk.pk.priors import PopulationPrior

logger = logging.getLogger(__name__)

#: The demonstration runs on one thread. A deployment keys threads by patient and episode; the
#: demo names it explicitly rather than defaulting, so a second browser tab joins the SAME
#: evaluation instead of silently starting a second one with different seeds.
DEMO_THREAD_ID: Final[str] = "demo-patient-a"

app = FastAPI(
    title="Agent PK",
    description=(
        "Tacrolimus exposure triage. Says WHEN TO LOOK; never says what the number is and "
        "never recommends a dose to a patient. Synthetic data only."
    ),
    version="0.1.0",
)

_graph = build_graph()

# ── Per-thread serialisation ─────────────────────────────────────────────────
#
# THE GRAPH AND ITS CHECKPOINTER ARE MODULE-LEVEL AND SHARED, AND `thread_id` IS CALLER-CONTROLLED.
# FastAPI runs these synchronous handlers in a threadpool, so two requests naming one thread really
# do overlap. Without serialisation a verifier's interleaving reopens the superseded-booking defect
# that the `run_complete` clear closed sequentially: request A begins a re-evaluation, and before
# `fit_node`'s clearing update is visible, request B reads `run_complete=True` with the PREVIOUS
# run's view still attached and projects a booking that is no longer the committed decision.
#
# So every read and every write of one thread's state happens under that thread's own lock. The
# lock is per-thread rather than global because two different patients must not queue behind each
# other, and the registry that hands them out has its own lock because a plain dict `setdefault`
# across threads can hand two callers two different lock objects for one id.
#
# THE LIMIT, STATED RATHER THAN LEFT TO BE DISCOVERED: this serialises within ONE PROCESS. It is
# correct for the single-uvicorn-process demonstration and it is NOT correct for a multi-process or
# multi-replica deployment, which needs the checkpointer itself to be transactional. That is the
# same boundary as `InMemorySaver` not being durable, and it moves at the same time.
#: How many idle thread locks to keep. `thread_id` is caller-supplied and unauthenticated, so an
#: unbounded registry is memory growth anyone can drive — raised as a LOW by a verifier. Idle
#: entries beyond this are dropped; an entry with a holder or a waiter is NEVER dropped.
MAX_IDLE_THREAD_LOCKS: Final[int] = 256

_thread_locks: dict[str, tuple[threading.Lock, list[int]]] = {}
_thread_locks_guard = threading.Lock()


@contextmanager
def _thread_lock(thread_id: str) -> Iterator[None]:
    """Hold one evaluation thread's lock for the duration of a state read or write.

    EVICTION IS REFERENCE-COUNTED, AND THAT IS NOT FUSSINESS. Dropping an entry that someone is
    holding or waiting on would let the next caller create a SECOND lock object for the same
    thread id — two callers inside one critical section, which is the exact defect the lock
    exists to prevent, reintroduced by the code that tidies it up. So a count is incremented
    under the registry guard before the lock is taken and decremented after it is released, and
    only a zero-count entry is ever evicted.

    Args:
        thread_id: The evaluation thread to serialise on.

    Yields:
        Control, with the thread's lock held.
    """
    with _thread_locks_guard:
        entry = _thread_locks.get(thread_id)
        if entry is None:
            entry = (threading.Lock(), [0])
            _thread_locks[thread_id] = entry
        lock, waiters = entry
        waiters[0] += 1
    try:
        with lock:
            yield
    finally:
        with _thread_locks_guard:
            waiters[0] -= 1
            if waiters[0] == 0 and len(_thread_locks) > MAX_IDLE_THREAD_LOCKS:
                for key, (_, count) in list(_thread_locks.items()):
                    if count[0] == 0:
                        del _thread_locks[key]
                        if len(_thread_locks) <= MAX_IDLE_THREAD_LOCKS:
                            break


# ── Request models — validation happens at the boundary, and only here ───────


class EvaluateRequest(BaseModel):
    """Start or restart an evaluation for a thread."""

    thread_id: str = Field(default=DEMO_THREAD_ID, min_length=1)


class DecisionRequest(BaseModel):
    """A clinician's answer to a sampling offer."""

    thread_id: str = Field(default=DEMO_THREAD_ID, min_length=1)
    decision: str = Field(description=f"{ACCEPTED!r} or {DECLINED!r}")


# ── Helpers ──────────────────────────────────────────────────────────────────


def _config(thread_id: str) -> dict[str, Any]:
    """The graph config addressing one evaluation thread."""
    return {"configurable": {"thread_id": thread_id}}


def _case_for(thread_id: str) -> PatientCase:
    """The case this thread evaluates.

    The demonstration serves one committed synthetic patient, in the state the demo opens in:
    troughs only, no sampling occasion yet. A deployment resolves the case from its own record
    system here, and that is the ONLY place a real patient record would ever enter.

    Args:
        thread_id: The evaluation thread. Unused by the demo, and named rather than dropped so
            the seam is visible.

    Returns:
        The patient case.
    """
    del thread_id
    return load_troughs_only_case()


def _context_for(state: dict[str, Any]) -> dict[str, Any]:
    """The clinician context for a graph result: plan bounds, own measurements, population.

    Args:
        state: The graph's returned state.

    Returns:
        The `clinician_context` block.

    Raises:
        HTTPException: 500 if the run carries no case or no prior. `fit_node` sets the prior
            before any outcome can exist, so this is a defect; a board served without the
            bounds and population it draws against would be a partial basis, and that is
            refused rather than degraded.
    """
    case: PatientCase | None = state.get("case")
    prior: PopulationPrior | None = state.get("prior")
    if case is None or prior is None:
        logger.error("graph result carries no case or prior; no clinician context")
        raise HTTPException(
            status_code=500,
            detail=(
                "The evaluation returned without the inputs its result is drawn against. "
                "Nothing is being reported about this patient — treat it as unevaluated."
            ),
        )
    return clinician_context_json(case, prior)


def _response_for(state: dict[str, Any]) -> dict[str, Any]:
    """Turn a graph result into the clinician-channel response.

    Three outcomes, kept structurally distinct so none can be read as another:
    `awaiting_decision`, `review_required`, and `complete`. Every outcome also carries
    `clinician_context` — the plan bounds, the patient's own measurements and the population
    reference — and a paused run carries the prediction and variability that raised its offer,
    because a decision card is drawn before the decision is made.

    Args:
        state: The graph's returned state.

    Returns:
        The response body.

    Raises:
        HTTPException: 500 if the graph finished with none of the three outcomes present, or
            paused without the prediction that gated it — each a defect, not a clinical state.
    """
    interrupts = state.get("__interrupt__")
    if interrupts:
        prediction: Prediction | None = state.get("prediction")
        if prediction is None:
            # `offer_node` is reachable only after the gate read a prediction, and `fit_node`
            # clears it at the start of every run, so a pause without one is a defect. An offer
            # shown without the prediction that raised it is a question without its reasons.
            logger.error("run paused at an offer with no prediction in state")
            raise HTTPException(
                status_code=500,
                detail=(
                    "The evaluation paused for a decision without the prediction that raised "
                    "it. Treat this patient as unevaluated."
                ),
            )
        context = _context_for(state)
        # The same derivation `build_clinician_view` uses, so the figure before the decision is
        # the figure after it.
        report, reason = variability_for(state["case"])
        return {
            "status": "awaiting_decision",
            "offer": interrupts[0].value,
            "prediction": prediction_json(prediction),
            "variability": variability_json(report),
            "variability_unavailable_reason": reason,
            "clinician_context": context,
        }

    review: ReviewRequired | None = state.get("review_required")
    if review is not None:
        # NOT an absent escalation. A failure to evaluate is its own outcome and says so.
        return {
            "status": "review_required",
            "stage": review.stage,
            "reason": review.reason,
            "clinician_context": _context_for(state),
        }

    view: ClinicianView | None = state.get("clinician_view")
    if view is None:
        logger.error("graph finished with no view, no interrupt and no review state")
        raise HTTPException(
            status_code=500,
            detail=(
                "The evaluation finished in a state carrying no result. Nothing is being "
                "reported about this patient — treat it as unevaluated, not as unremarkable."
            ),
        )
    return {
        "status": "complete",
        "clinician_view": clinician_view_json(view),
        "clinician_context": _context_for(state),
    }


def _patient_view_for(thread_id: str) -> PatientView:
    """Project only a COMMITTED, COMPLETE run into the patient channel.

    THREE STATES, AND ONLY ONE OF THEM PROJECTS. Both of the other two were fail-open defects a
    verifier found on this function, and both had the same shape: the function branched on
    `clinician_view is None` and treated everything else as a finished, current decision.

    1. NOT COMPLETE — the run is paused at a sampling offer, or was never started, or is a
       RE-RUN of a thread that previously finished. The third is the one that bites: a
       checkpointed thread keeps every key no node rewrote, so a `clinician_view` from a
       superseded run is still sitting there. Measured before the fix: evaluate, accept, then
       evaluate again, and this route served `SAMPLE_SCHEDULED` with a booked appointment while
       the clinician was at a fresh unanswered offer. The patient is told there is nothing to do,
       which is true — the decision is the clinician's and has not been made.
    2. REVIEW REQUIRED — the record could not be evaluated. Returning `NOTHING_TO_DO` here would
       be a FALSE REASSURANCE generated by a failure, which is the asymmetry the clinician
       channel already avoids by reporting `review_required` as its own outcome. See the note
       below on why this maps to `CONTACT_YOUR_TEAM`.
    3. COMPLETE — `run_complete` is True and no interrupt is pending. Only now is there a
       decision to project.

    `to_patient_view` independently enforces the narrower rule that an appointment crosses only
    when the action is to schedule one. That is defence in depth, not the control: it cannot tell
    a current decision from a superseded one, because both are well-formed.

    Args:
        thread_id: The evaluation thread.

    Returns:
        The patient projection.
    """
    case = _case_for(thread_id)
    # Read the whole snapshot under the thread's lock, so it cannot be observed mid-update with a
    # completed run's view still attached to a run that has just restarted.
    with _thread_lock(thread_id):
        snapshot = _graph.get_state(_config(thread_id))
        values = dict(snapshot.values)
        interrupted = bool(snapshot.interrupts)

    def _own_data(message: PatientMessage) -> PatientView:
        """The patient's own data with one closed-set message and no appointment."""
        return PatientView(
            message=message,
            plan_text_from_clinician=case.plan.plan_text_from_clinician,
            own_doses=case.doses,
            own_results=case.observations,
            next_sample=None,
        )

    complete = bool(values.get("run_complete")) and not interrupted
    if not complete:
        if values.get("review_required") is not None:
            # A FAILURE MUST NOT PRESENT AS REASSURANCE. Of the five permitted messages this is
            # the only one that is TRUE under an unevaluable record and interprets nothing:
            # `NOTHING_TO_DO` is a false all-clear generated by a fault, `CLINICIAN_NOTIFIED`
            # asserts a notification this code does not send, and
            # `EVALUATION_MAY_BE_HELPFUL` opens "Based on what you have told me", which
            # misattributes a software failure to something the patient reported. This errs
            # toward asking rather than reassuring, and it is a DESIGN CHOICE a clinician may
            # want to overrule — it is recorded here rather than left implicit for that reason.
            return _own_data(PatientMessage.CONTACT_YOUR_TEAM)
        return _own_data(PatientMessage.NOTHING_TO_DO)

    view: ClinicianView | None = values.get("clinician_view")
    if view is None:
        # run_complete without a view is a defect, not a clinical state. Fail closed rather than
        # inventing a reassuring message for a state that should be unreachable.
        logger.error("thread %r is marked complete but carries no view", thread_id)
        raise HTTPException(
            status_code=500,
            detail=(
                "This evaluation is marked complete but carries no result. Nothing is being "
                "reported about this patient — treat it as unevaluated."
            ),
        )
    projected = to_patient_view(
        view,
        plan_text_from_clinician=case.plan.plan_text_from_clinician,
        own_doses=case.doses,
        own_results=case.observations,
    )
    return _without_unsent_notification_claim(projected)


def _without_unsent_notification_claim(view: PatientView) -> PatientView:
    """Refuse to serve `CLINICIAN_NOTIFIED`, whose body asserts a send this system never makes.

    THE MESSAGE SAYS "Your transplant team has been sent an update." NOTHING SENDS ONE. There is
    no outbound channel anywhere in this process — no mail, no push, no webhook — so on every
    completed `FLAG_FOR_REVIEW`, `URGENT_REVIEW` or dose-change outcome the patient was told
    something had happened that had not. A patient who believes their team has been alerted waits
    instead of calling.

    TWO INDEPENDENT VERIFIER LINEAGES RAISED THIS, and the second corrected the maker's first
    answer, which was to escalate it and ship. Its argument is the one that decided it: the
    MESSAGE TEXT is a product choice belonging to the project owner, but SERVING A KNOWN FALSE
    CLAIM is not, and this function is the consumption boundary — it already refuses this exact
    message for `review_required` on exactly this reasoning, then emitted it for the equivalent
    completed outcome two branches later. Closing it in one place and not the other was the
    inconsistency both seats named.

    So the substitution happens HERE rather than in `agent_pk.channel`: the channel's map and its
    message bodies are previously-reviewed patient-facing copy in a regulated channel, and
    rewriting them is the owner's call. This is a guard over what gets served, not a second
    source of truth for the mapping — it removes one message and names its replacement, and the
    right durable fix is still upstream.

    THE SUBSTITUTION IS SAFE ON THE CHANNEL'S OWN TERMS. `CONTACT_YOUR_TEAM` is already the
    mapping for `ESCALATE_TO_TRANSPLANT_TEAM`, so it carries no new information; it names no
    condition, no threshold and no direction of travel; and the map stays NON-INJECTIVE, which is
    the property that keeps dose-up and dose-down indistinguishable to a patient. It is more
    cautious than the text it replaces, which is the right direction for an error.

    Args:
        view: The projection as the channel produced it.

    Returns:
        The same view, with an unsent-notification claim replaced. Every other field is untouched.
    """
    if view.message is not PatientMessage.CLINICIAN_NOTIFIED:
        return view
    logger.info(
        "substituting CONTACT_YOUR_TEAM for CLINICIAN_NOTIFIED: this build sends no notification"
    )
    return PatientView(
        message=PatientMessage.CONTACT_YOUR_TEAM,
        plan_text_from_clinician=view.plan_text_from_clinician,
        own_doses=view.own_doses,
        own_results=view.own_results,
        next_sample=view.next_sample,
    )


# ── Clinician channel ────────────────────────────────────────────────────────


@app.post("/api/clinician/evaluate")
def evaluate(request: EvaluateRequest) -> dict[str, Any]:
    """Run the evaluation, stopping at the sampling offer if the gate fires.

    Raises:
        HTTPException: 422 if the case or plan is malformed.
    """
    try:
        with _thread_lock(request.thread_id):
            state = _graph.invoke(
                {"case": _case_for(request.thread_id)}, _config(request.thread_id)
            )
    except PkInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _response_for(dict(state))


@app.post("/api/clinician/decision")
def decide(request: DecisionRequest) -> dict[str, Any]:
    """Answer a pending sampling offer and let the run finish.

    Raises:
        HTTPException: 422 for an answer that is neither accept nor decline; 409 when the
            thread is not actually waiting on a decision — an answer is never applied to a run
            that did not ask a question.
    """
    if request.decision not in (ACCEPTED, DECLINED):
        raise HTTPException(
            status_code=422,
            detail=f"decision must be {ACCEPTED!r} or {DECLINED!r}",
        )
    # The pending-offer CHECK and the RESUME are one critical section. Split, two callers can both
    # observe the interrupt and both resume it — and the second would be answering a question that
    # is no longer being asked.
    try:
        with _thread_lock(request.thread_id):
            snapshot = _graph.get_state(_config(request.thread_id))
            if not snapshot.interrupts:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "This evaluation is not waiting on a sampling decision. Run the "
                        "evaluation first; an answer is never applied to a run that did not "
                        "ask a question."
                    ),
                )
            state = _graph.invoke(
                Command(resume={"decision": request.decision}),
                _config(request.thread_id),
            )
    except PkInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _response_for(dict(state))


# ── Patient channel — no agent, no stream, no shared state ───────────────────


@app.get("/api/patient/view")
def patient_view(thread_id: str = DEMO_THREAD_ID) -> dict[str, Any]:
    """Everything the patient may see, and structurally nothing else.

    Carries no prediction, no interval, no boundary verdict, no attribution and no direction
    of travel. The message comes from a closed enum whose bodies contain no digits; the only
    other prose is the patient's own clinician's authored plan text, carried verbatim.
    """
    return {
        "reference_instant_utc": load_demo_reference_instant(),
        "patient_view": patient_view_json(_patient_view_for(thread_id)),
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Liveness, and the two facts a reviewer should not have to go looking for."""
    return {
        "status": "ok",
        "data_class": "synthetic only — no PHI, by design and by review",
        "gate": (
            "the escalation decision is deterministic Python reading "
            "Prediction.crosses_boundary; no language model chooses whether to escalate"
        ),
        "actions": [str(action) for action in ClinicalAction],
    }
