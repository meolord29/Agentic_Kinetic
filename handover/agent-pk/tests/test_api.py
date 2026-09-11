"""The HTTP surface, and above all the channel boundary it must not undo.

`test_the_patient_route_carries_no_clinician_field` is the cheapest guarantee in the build and
the reason this file exists. Everything else here is ordinary route behaviour; that one is the
permission boundary, checked at the last layer a field could escape from.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from agent_pk.agent.case import PatientCase, ReviewRequired
from agent_pk.agent.demo_case import load_troughs_only_case
from agent_pk.agent.graph import ACCEPTED, DECLINED
from agent_pk.api import app as app_module
from agent_pk.channel import (
    PATIENT_MESSAGE_BODY,
    ClinicalAction,
    ClinicianView,
    EvidenceNote,
    ParameterEstimate,
    PatientMessage,
    SampleAppointment,
)
from agent_pk.pk import priors
from agent_pk.pk.fit import Prediction

#: See tests/test_agent_graph.py for why the offer forecast is averaged over fewer futures
#: here. These tests assert routing and the channel boundary, neither of which it touches.
FAST_SIMULATIONS = 4


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A client whose evaluations use the reduced forecast setting."""

    def _fast_case(thread_id: str) -> PatientCase:
        del thread_id
        return dataclasses.replace(
            load_troughs_only_case(), offer_simulations=FAST_SIMULATIONS
        )

    monkeypatch.setattr(app_module, "_case_for", _fast_case)
    with TestClient(app_module.app) as test_client:
        yield test_client


def _clinician_view_with(
    action: ClinicalAction, appointment: SampleAppointment | None
) -> ClinicianView:
    """A minimal but COMPLETE clinician view, for exercising the projection over every action.

    Built in full rather than with a stub, because `ClinicianView` refuses construction without
    its basis — which is criterion 4 as a constructor signature, and is exactly the property a
    convenience stub in a test would quietly route around.
    """
    return ClinicianView(
        action=action,
        prediction=Prediction(
            time_h=1.0,
            median_ng_per_ml=7.0,
            lower_ng_per_ml=6.0,
            upper_ng_per_ml=8.0,
            credible_mass=0.90,
            crosses_below=False,
            crosses_above=False,
            probability_below=0.01,
            probability_above=0.01,
            usable_fraction=1.0,
            haematocrit_known=True,
        ),
        parameters=(
            ParameterEstimate(
                label="Apparent clearance (CL/F)",
                value=30.0,
                lower=20.0,
                upper=40.0,
                unit="L/h",
            ),
        ),
        attributions=(),
        evidence=(
            EvidenceNote(
                claim="a cited claim", source_url="https://example.invalid/doi"
            ),
        ),
        n_observations=4,
        calibration_note="a note",
        proposed_sampling=appointment,
        variability=None,
        variability_unavailable_reason="fewer troughs than the measures need",
    )


def _evaluate(client: TestClient, thread: str) -> dict[str, Any]:
    response = client.post("/api/clinician/evaluate", json={"thread_id": thread})
    assert response.status_code == 200, response.text
    return response.json()


# ── The channel boundary ─────────────────────────────────────────────────────


def test_the_patient_route_carries_no_clinician_field(client: TestClient) -> None:
    """No prediction, no interval, no boundary verdict, no attribution, no direction.

    Asserted as a RECURSIVE SEARCH OVER THE WHOLE RESPONSE rather than a check of the top-level
    keys: a leak that mattered would arrive nested, and a top-level check would pass over it.
    """
    _evaluate(client, "boundary")
    client.post(
        "/api/clinician/decision", json={"thread_id": "boundary", "decision": ACCEPTED}
    )
    body = client.get("/api/patient/view", params={"thread_id": "boundary"}).json()

    forbidden = {
        "prediction",
        "median_ng_per_ml",
        "lower_ng_per_ml",
        "upper_ng_per_ml",
        "crosses_below",
        "crosses_above",
        "crosses_boundary",
        "probability_below",
        "probability_above",
        "attributions",
        "parameters",
        "evidence",
        "calibration_note",
        "variability",
        "action",
        "clinician_view",
        "clinician_context",
        "population_reference",
        "plan",
        "lower_bound_ng_per_ml",
        "upper_bound_ng_per_ml",
        "band_citation",
        "own_troughs",
        "own_curve_samples",
        "target_time_h",
        "next_dose_time_h",
        "typical",
        "interval_mass",
        "genotype_known",
        "source_url",
        "ipv_percent",
        "time_in_range_percent",
    }
    found: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in forbidden:
                    found.append(f"{path}.{key}")
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(body, "$")
    assert not found, f"clinician-channel fields reached the patient route: {found}"


def test_no_software_authored_patient_string_contains_a_digit(
    client: TestClient,
) -> None:
    """The patient message set is closed and its bodies carry no digits, by construction.

    THE EXEMPTIONS ARE NAMED, and naming them is the point. `plan_text_from_clinician` is the
    clinician's OWN words, permitted verbatim under 360j(o)(1)(D), and the patient's own doses,
    own results and appointment times are their own data and logistics. Everything the SOFTWARE
    itself says is checked.
    """
    _evaluate(client, "digits")
    body = client.get("/api/patient/view", params={"thread_id": "digits"}).json()
    view = body["patient_view"]
    assert not any(character.isdigit() for character in view["body"]), view["body"]
    for message in PatientMessage:
        text = PATIENT_MESSAGE_BODY[message]
        assert not any(c.isdigit() for c in text), f"{message}: {text}"


def test_a_pending_offer_does_not_reach_the_patient_as_a_booking(
    client: TestClient,
) -> None:
    """A proposal the clinician has not accepted must not appear on a patient's phone."""
    result = _evaluate(client, "pending")
    assert result["status"] == "awaiting_decision"
    view = client.get("/api/patient/view", params={"thread_id": "pending"}).json()[
        "patient_view"
    ]
    assert view["next_sample"] is None
    assert view["message"] == str(PatientMessage.NOTHING_TO_DO)


def test_a_declined_offer_does_not_reach_the_patient_as_a_booking(
    client: TestClient,
) -> None:
    """Declining schedules nothing, and the patient is told nothing about the crossing."""
    _evaluate(client, "declined")
    client.post(
        "/api/clinician/decision", json={"thread_id": "declined", "decision": DECLINED}
    )
    view = client.get("/api/patient/view", params={"thread_id": "declined"}).json()[
        "patient_view"
    ]
    assert view["next_sample"] is None
    # NOT `CLINICIAN_NOTIFIED`, whose body claims "your transplant team has been sent an update"
    # while no outbound channel exists anywhere in this process. Two verifier lineages raised
    # that independently; the route refuses to serve the claim. See
    # `_without_unsent_notification_claim`.
    assert view["message"] == str(PatientMessage.CONTACT_YOUR_TEAM)
    assert "sent an update" not in view["body"]


def test_an_accepted_offer_reaches_the_patient_as_logistics_only(
    client: TestClient,
) -> None:
    """The appointment crosses; the reason for it does not."""
    _evaluate(client, "accepted")
    client.post(
        "/api/clinician/decision", json={"thread_id": "accepted", "decision": ACCEPTED}
    )
    view = client.get("/api/patient/view", params={"thread_id": "accepted"}).json()[
        "patient_view"
    ]
    assert view["next_sample"] is not None
    assert view["next_sample"]["offsets_post_dose_h"] == [0.0, 1.0, 3.0, 6.0]
    assert view["message"] == str(PatientMessage.SAMPLE_SCHEDULED)


def test_re_evaluating_does_not_leave_a_superseded_booking_on_the_patient_view(
    client: TestClient,
) -> None:
    """The defect a verifier found and a reproduction confirmed, pinned so it cannot return.

    A checkpointed thread keeps every key no node rewrote, so the `clinician_view` from a
    FINISHED run was still present when a new run started. The patient route branched on
    `clinician_view is None`, read the superseded decision as current, and served
    `SAMPLE_SCHEDULED` with a booked appointment while the clinician sat at a fresh unanswered
    offer. Reproduced against the original code before the fix.

    MUTATION-CHECKED, AND THE RESULT IS WORTH RECORDING because the first claim written here was
    wrong. The defect is closed at TWO layers — `fit_node` clears the previous run's outcomes,
    and this route requires a positive `run_complete` — and EITHER ALONE closes it. So reverting
    one layer leaves this test passing, and only reverting BOTH reproduces the failure. That is
    defence in depth working as intended, but it means a single-mutant check on either layer
    reads as "the test does not catch it": measured, both mutants together fail this test with
    "a superseded booking survived into the new run", and neither does alone.
    """
    assert _evaluate(client, "supersede")["status"] == "awaiting_decision"
    accepted = client.post(
        "/api/clinician/decision", json={"thread_id": "supersede", "decision": ACCEPTED}
    ).json()
    assert accepted["status"] == "complete"
    booked = client.get("/api/patient/view", params={"thread_id": "supersede"}).json()[
        "patient_view"
    ]
    assert booked["next_sample"] is not None, (
        "precondition: the first run booked a sample"
    )

    # Start again. The clinician is now at a NEW, unanswered offer.
    assert _evaluate(client, "supersede")["status"] == "awaiting_decision"
    after = client.get("/api/patient/view", params={"thread_id": "supersede"}).json()[
        "patient_view"
    ]
    assert after["next_sample"] is None, (
        "a superseded booking survived into the new run"
    )
    assert after["message"] == str(PatientMessage.NOTHING_TO_DO)


def test_an_unevaluable_record_is_not_reported_to_the_patient_as_nothing_to_do(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure must not present as reassurance.

    The clinician channel already reports `review_required` as its own outcome. The patient
    route read only `clinician_view`, so the same state returned HTTP 200 and "nothing for you
    to do right now" — an all-clear generated by a fault. Asymmetric fail-open, found by a
    verifier on the consumption boundary.

    The degenerate prediction is INJECTED, because the branch under test is this layer's
    handling of it rather than the numeric core's decision to produce one.
    """
    import agent_pk.agent.graph as graph_module

    def _degenerate(case: object, fit: object) -> ReviewRequired:
        del case, fit
        return ReviewRequired(stage="prediction", reason="injected for this test")

    monkeypatch.setattr(graph_module, "predict_case", _degenerate)

    result = _evaluate(client, "unevaluable")
    assert result["status"] == "review_required", result
    view = client.get("/api/patient/view", params={"thread_id": "unevaluable"}).json()[
        "patient_view"
    ]
    assert view["message"] != str(PatientMessage.NOTHING_TO_DO)
    assert view["message"] == str(PatientMessage.CONTACT_YOUR_TEAM)
    assert view["next_sample"] is None
    assert not any(character.isdigit() for character in view["body"])


def test_a_review_required_result_still_carries_its_context(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unevaluable record is shown to the clinician against the same plan and measurements.

    The review card names what could not be evaluated; the band, troughs and population it would
    have been judged against are still the patient's own, and a board drawn without them would
    turn a failure to evaluate into a card with no basis at all. Injected the same way as above.
    """
    import agent_pk.agent.graph as graph_module

    def _degenerate(case: object, fit: object) -> ReviewRequired:
        del case, fit
        return ReviewRequired(stage="prediction", reason="injected for this test")

    monkeypatch.setattr(graph_module, "predict_case", _degenerate)

    result = _evaluate(client, "unevaluable-context")
    assert result["status"] == "review_required", result
    context = result["clinician_context"]
    case = load_troughs_only_case()
    assert context["plan"]["lower_bound_ng_per_ml"] == case.plan.lower_bound_ng_per_ml
    assert len(context["own_troughs"]) == len(case.troughs)
    assert context["population_reference"]["typical"] > 0.0
    assert "prediction" not in result


def test_a_stale_review_required_does_not_survive_into_a_healthy_run(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same staleness, in the other direction: a cleared failure must not keep alarming.

    Without the per-run clear, a thread that once failed would keep telling the patient to
    contact their team forever, including after a later run completed normally.
    """
    import agent_pk.agent.graph as graph_module

    def _degenerate(case: object, fit: object) -> ReviewRequired:
        del case, fit
        return ReviewRequired(stage="prediction", reason="injected for this test")

    monkeypatch.setattr(graph_module, "predict_case", _degenerate)
    assert _evaluate(client, "recovers")["status"] == "review_required"
    monkeypatch.undo()

    assert _evaluate(client, "recovers")["status"] == "awaiting_decision"
    view = client.get("/api/patient/view", params={"thread_id": "recovers"}).json()[
        "patient_view"
    ]
    assert view["message"] == str(PatientMessage.NOTHING_TO_DO)


def test_one_thread_is_never_inside_the_graph_twice_at_once(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requests naming one evaluation thread must not overlap inside the graph.

    A verifier's interleaving reopens the superseded-booking defect that `run_complete` closed
    sequentially: request A begins a re-evaluation, and before `fit_node`'s clearing update is
    visible, request B reads `run_complete=True` with the PREVIOUS run's view still attached.

    THE PROPERTY IS ASSERTED DIRECTLY RATHER THAN BY RACING FOR THE SYMPTOM. A stress test that
    waits for a stale booking to appear passes whenever the interleaving happens not to occur,
    which is most runs — it would report the lock working while proving nothing. So the graph
    calls are instrumented and the test asserts the invariant the lock exists to create: at no
    moment is more than one caller inside one thread's critical section.
    """
    depth = 0
    max_depth = 0
    depth_guard = threading.Lock()
    real_invoke = m_graph_invoke = app_module._graph.invoke
    real_get_state = app_module._graph.get_state

    def _track(fn: Any) -> Any:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            nonlocal depth, max_depth
            with depth_guard:
                depth += 1
                max_depth = max(max_depth, depth)
            try:
                time.sleep(0.01)  # widen the window a real race would need
                return fn(*args, **kwargs)
            finally:
                with depth_guard:
                    depth -= 1

        return wrapper

    monkeypatch.setattr(app_module._graph, "invoke", _track(real_invoke))
    monkeypatch.setattr(app_module._graph, "get_state", _track(real_get_state))
    assert m_graph_invoke is real_invoke  # the original is captured, not the wrapper

    errors: list[BaseException] = []

    def hammer(index: int) -> None:
        try:
            client.post("/api/clinician/evaluate", json={"thread_id": "race"})
            client.get("/api/patient/view", params={"thread_id": "race"})
            client.post(
                "/api/clinician/decision",
                json={"thread_id": "race", "decision": DECLINED},
            )
            client.get("/api/patient/view", params={"thread_id": "race"})
        except BaseException as exc:  # noqa: BLE001 - re-raised in the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(i,)) for i in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=300)

    assert not errors, f"a concurrent request raised: {errors[0]!r}"
    assert all(not thread.is_alive() for thread in threads), "a request deadlocked"
    assert max_depth == 1, (
        f"{max_depth} callers were inside one thread's critical section at once; "
        "the per-thread lock is not serialising graph access"
    )


def test_the_lock_registry_is_bounded_and_never_evicts_a_held_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`thread_id` is unauthenticated, so an unbounded lock registry is caller-driven growth.

    The second assertion is the one that matters. Evicting an entry someone is holding would let
    the next caller create a SECOND lock object for the same id — two callers inside one critical
    section, the exact defect the lock exists to prevent, reintroduced by the tidy-up. So a held
    entry must survive eviction pressure, and the object handed out afterwards must be the SAME
    one.
    """
    monkeypatch.setattr(app_module, "MAX_IDLE_THREAD_LOCKS", 4)
    monkeypatch.setattr(app_module, "_thread_locks", {})

    for index in range(40):
        with app_module._thread_lock(f"caller-{index}"):
            pass
    assert len(app_module._thread_locks) <= 5, (
        f"registry grew to {len(app_module._thread_locks)} under a cap of 4"
    )

    held_seen: list[int] = []
    started = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with app_module._thread_lock("held"):
            held_seen.append(id(app_module._thread_locks["held"][0]))
            started.set()
            release.wait(timeout=10)

    holder = threading.Thread(target=hold)
    holder.start()
    assert started.wait(timeout=10), "the holding thread never entered the section"

    # Drive eviction hard while "held" is occupied.
    for index in range(40):
        with app_module._thread_lock(f"pressure-{index}"):
            pass
    assert "held" in app_module._thread_locks, "a HELD lock was evicted"
    held_seen.append(id(app_module._thread_locks["held"][0]))

    release.set()
    holder.join(timeout=10)
    assert not holder.is_alive()
    assert held_seen[0] == held_seen[1], (
        "the held thread id was handed a different lock object after eviction pressure"
    )


def test_the_patient_is_never_told_of_a_notification_nothing_sends(
    client: TestClient,
) -> None:
    """No served patient message may assert that the team was contacted.

    The property, not one example: this build has no outbound channel at all, so ANY route out of
    the patient endpoint that produces "has been sent an update" is a false statement to a patient
    who may then wait instead of calling. Asserted over every action the gate can produce.
    """
    from agent_pk.channel import to_patient_view

    forbidden_body = PATIENT_MESSAGE_BODY[PatientMessage.CLINICIAN_NOTIFIED]
    for action in ClinicalAction:
        appointment = None
        if action is ClinicalAction.SCHEDULE_ADDITIONAL_PK_SAMPLE:
            appointment = SampleAppointment(
                start_time_h=0.0, offsets_post_dose_h=(0.0,), fasted_required=True
            )
        projected = to_patient_view(
            _clinician_view_with(action, appointment),
            plan_text_from_clinician="clinician text",
            own_doses=(),
            own_results=(),
        )
        served = app_module._without_unsent_notification_claim(projected)
        assert served.body != forbidden_body, (
            f"action {action} serves a claim that a notification was sent"
        )


# ── Clinician channel behaviour ──────────────────────────────────────────────


def test_the_clinician_payload_carries_its_complete_basis(client: TestClient) -> None:
    """A recommendation serialised without its basis is criterion 4 failing one layer down."""
    _evaluate(client, "basis")
    result = client.post(
        "/api/clinician/decision", json={"thread_id": "basis", "decision": ACCEPTED}
    ).json()
    view = result["clinician_view"]
    assert view["parameters"], "no fitted parameters"
    assert view["evidence"], "no citations"
    assert all(note["source_url"] for note in view["evidence"])
    assert view["prediction"]["crosses_boundary"] is True
    assert view["n_observations"] == 4


def test_a_pending_offer_carries_what_the_board_decides_on(client: TestClient) -> None:
    """The decision card is drawn BEFORE anyone answers, so its reasons must arrive with it.

    Before this, `awaiting_decision` carried only the offer: the chance of a low trough, the
    predicted range, the plan's bounds and the patient's troughs existed only once the clinician
    had already decided — a board could not show why it was asking at the moment it asked.
    """
    body = _evaluate(client, "pending-board")
    assert body["status"] == "awaiting_decision"

    prediction = body["prediction"]
    assert prediction["crosses_boundary"] is True
    assert 0.0 <= prediction["probability_below"] <= 1.0
    assert (
        prediction["lower_ng_per_ml"]
        <= prediction["median_ng_per_ml"]
        <= prediction["upper_ng_per_ml"]
    )
    if body["variability"] is None:
        assert body["variability_unavailable_reason"].strip()
    else:
        assert body["variability_unavailable_reason"] == ""

    case = load_troughs_only_case()
    context = body["clinician_context"]
    assert context["plan"]["lower_bound_ng_per_ml"] == case.plan.lower_bound_ng_per_ml
    assert context["plan"]["upper_bound_ng_per_ml"] == case.plan.upper_bound_ng_per_ml
    assert context["plan"]["band_citation"].strip()
    assert [t["concentration_ng_per_ml"] for t in context["own_troughs"]] == [
        t.concentration_ng_per_ml for t in case.troughs
    ]
    assert len(context["own_doses"]) == len(case.doses)


def test_the_population_reference_is_the_published_typical_value_and_spread(
    client: TestClient,
) -> None:
    """Checked against the source's own estimates, not against the code that computes them.

    The demo patient is a 70 kg CYP3A5 expresser with no age term, which is the source's
    reference group, so the typical clearance must be theta_1 itself. The range is the central
    90% of the published between-patient variability (CV 32.1%) around it: 15.83 to 44.36 L/h.
    """
    body = _evaluate(client, "population")
    reference = body["clinician_context"]["population_reference"]
    assert reference["typical"] == pytest.approx(priors.CL_F_CARRIER_L_PER_H_70KG)
    assert reference["lower"] == pytest.approx(15.83, abs=0.01)
    assert reference["upper"] == pytest.approx(44.36, abs=0.01)
    assert reference["interval_mass"] == pytest.approx(0.90)
    assert reference["unit"] == "L/h"
    assert reference["population_limit"] == priors.SOURCE_POPULATION_LIMIT
    assert reference["source_url"] == priors.SOURCE_URL


def test_the_context_is_unchanged_by_the_decision(client: TestClient) -> None:
    """The answer changes the action, never the plan, measurements or population drawn beside it."""
    pending = _evaluate(client, "context-stable")
    done = client.post(
        "/api/clinician/decision",
        json={"thread_id": "context-stable", "decision": ACCEPTED},
    ).json()
    assert done["status"] == "complete"
    assert done["clinician_context"] == pending["clinician_context"]
    assert (
        done["clinician_context"]["population_reference"]["label"]
        == done["clinician_view"]["parameters"][0]["label"]
    )
    # The variability shown before the decision is the variability in the view after it.
    assert done["clinician_view"]["variability"] == pending["variability"]
    assert (
        done["clinician_view"]["variability_unavailable_reason"]
        == pending["variability_unavailable_reason"]
    )


def test_the_context_travels_with_a_declined_decision(client: TestClient) -> None:
    """Declining turns the action into a review flag; the basis drawn beside it is still served."""
    pending = _evaluate(client, "context-declined")
    done = client.post(
        "/api/clinician/decision",
        json={"thread_id": "context-declined", "decision": DECLINED},
    ).json()
    assert done["status"] == "complete"
    assert done["clinician_view"]["action"] == str(ClinicalAction.FLAG_FOR_REVIEW)
    assert done["clinician_context"] == pending["clinician_context"]


def test_an_absent_variability_always_carries_its_reason(client: TestClient) -> None:
    """Absent must never be readable as normal — the defect this project produced twice."""
    _evaluate(client, "variability")
    view = client.post(
        "/api/clinician/decision",
        json={"thread_id": "variability", "decision": ACCEPTED},
    ).json()["clinician_view"]
    if view["variability"] is None:
        assert view["variability_unavailable_reason"].strip()
    else:
        assert view["variability_unavailable_reason"] == ""


def test_a_decision_with_no_pending_offer_is_refused(client: TestClient) -> None:
    """An answer is never applied to a run that did not ask a question."""
    response = client.post(
        "/api/clinician/decision", json={"thread_id": "unasked", "decision": ACCEPTED}
    )
    assert response.status_code == 409


def test_an_unrecognised_decision_is_refused(client: TestClient) -> None:
    """There is no default, because the default would suppress the escalation."""
    _evaluate(client, "garbage")
    response = client.post(
        "/api/clinician/decision", json={"thread_id": "garbage", "decision": "sure"}
    )
    assert response.status_code == 422


def test_answering_twice_is_refused(client: TestClient) -> None:
    """The second answer has no question to answer, and must not restart the run."""
    _evaluate(client, "twice")
    first = client.post(
        "/api/clinician/decision", json={"thread_id": "twice", "decision": DECLINED}
    )
    assert first.status_code == 200
    second = client.post(
        "/api/clinician/decision", json={"thread_id": "twice", "decision": ACCEPTED}
    )
    assert second.status_code == 409


def test_health_states_the_two_facts_a_reviewer_needs(client: TestClient) -> None:
    """Data class and where the escalation decision is made, without going looking."""
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert "synthetic" in body["data_class"]
    assert "no language model" in body["gate"]
