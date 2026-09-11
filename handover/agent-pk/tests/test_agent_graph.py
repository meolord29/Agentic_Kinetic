"""The evaluation graph: what it decides, what it refuses, and what it does not decide.

The tests that matter here are the NEGATIVE ones. A happy path through this graph passes on a
version whose gate consults a language model, whose degenerate prediction silently becomes
`NO_ACTION`, and whose unrecognised decision defaults to "declined" — so each of those is
asserted directly rather than inferred from a green run.
"""

from __future__ import annotations

import dataclasses

import pytest
from langgraph.types import Command

from agent_pk.agent.case import CarePlan, PatientCase, ReviewRequired
from agent_pk.agent.demo_case import load_demo_case, load_troughs_only_case
from agent_pk.agent.evaluate import attributions_for, gate_action, predict_case
from agent_pk.agent.graph import (
    ACCEPTED,
    DECLINED,
    PER_RUN_OUTCOME_KEYS,
    PkAgentState,
    build_graph,
    fit_node,
    offer_node,
    route_after_gate,
    route_after_predict,
)
from agent_pk.channel import ClinicalAction
from agent_pk.pk.calibration import CalibrationError, SamplingOffer
from agent_pk.pk.fit import Prediction, fit_individual
from agent_pk.pk.model import DoseEvent, Observation, PkInputError
from agent_pk.pk.priors import prior_for


#: Simulated futures these tests average the offer over. FOUR, NOT THE DEMONSTRATION'S
#: TWENTY-FOUR, and stated here rather than left implicit: at the committed setting each run
#: costs about forty seconds and this file needs several, which took the suite to nine minutes.
#: Every assertion below is about STRUCTURE or ORDERING — which key the card leads with, that
#: two answers differ, that a bad answer raises — none of which the count changes. The one test
#: that must see the real numbers says so in its own name and pays the cost.
FAST_SIMULATIONS = 4


def _fast_case() -> PatientCase:
    """The demo patient, with the offer forecast averaged over fewer futures. See above."""
    return dataclasses.replace(
        load_troughs_only_case(), offer_simulations=FAST_SIMULATIONS
    )


def _run_to_offer(
    thread: str, case: PatientCase | None = None
) -> tuple[object, dict, dict]:
    """Run a case up to the sampling offer. Returns (graph, config, state)."""
    graph = build_graph()
    config = {"configurable": {"thread_id": thread}}
    state = graph.invoke({"case": case or _fast_case()}, config)
    return graph, config, dict(state)


# ── The gate ─────────────────────────────────────────────────────────────────


def test_the_gate_reads_only_the_boundary_verdict() -> None:
    """`gate_action` must depend on `crosses_boundary` and on nothing else.

    Two predictions identical in every field EXCEPT the boundary verdicts must produce
    different actions, and two that differ in every OTHER field must produce the same one.
    That is the property the regulatory argument rests on, and it is stronger than checking a
    single example.
    """
    inside = Prediction(
        time_h=719.75,
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
    )
    crossing = dataclasses.replace(inside, crosses_below=True, probability_below=0.4)
    assert gate_action(inside) is ClinicalAction.NO_ACTION
    assert gate_action(crossing) is ClinicalAction.SCHEDULE_ADDITIONAL_PK_SAMPLE

    # Everything else moved; the verdict did not. The action must not move either.
    noisy = dataclasses.replace(
        inside,
        median_ng_per_ml=4.9,
        lower_ng_per_ml=1.0,
        upper_ng_per_ml=99.0,
        probability_below=0.49,
        probability_above=0.49,
        usable_fraction=0.51,
        haematocrit_known=False,
    )
    assert gate_action(noisy) is ClinicalAction.NO_ACTION


def test_an_interval_crossing_both_bounds_names_no_direction() -> None:
    """A prediction that reaches BOTH boundaries supports neither direction.

    Naming one would put a claim on the clinician's basis panel that the evidence does not
    carry — and the panel is the one place a clinician is entitled to trust. Raised as an
    uncertainty by the Stage-A verifier against the earlier form, which reported "raises".
    """
    both = Prediction(
        time_h=719.75,
        median_ng_per_ml=7.0,
        lower_ng_per_ml=3.0,
        upper_ng_per_ml=14.0,
        credible_mass=0.90,
        crosses_below=True,
        crosses_above=True,
        probability_below=0.3,
        probability_above=0.3,
        usable_fraction=1.0,
        haematocrit_known=True,
    )
    (attribution,) = attributions_for(both)
    assert attribution.direction == "unexplained"
    assert attribution.magnitude_ng_per_ml is None, "an absent magnitude is not zero"

    below_only = dataclasses.replace(both, crosses_above=False, probability_above=0.01)
    assert attributions_for(below_only)[0].direction == "lowers"
    above_only = dataclasses.replace(both, crosses_below=False, probability_below=0.01)
    assert attributions_for(above_only)[0].direction == "raises"


def test_no_action_routes_past_the_offer_entirely() -> None:
    """A patient who is not crossing is never asked for extra blood."""
    assert route_after_gate({"action": ClinicalAction.NO_ACTION}) == "view"
    assert (
        route_after_gate({"action": ClinicalAction.SCHEDULE_ADDITIONAL_PK_SAMPLE})
        == "offer"
    )


# ── The pause ────────────────────────────────────────────────────────────────


def test_a_crossing_stops_the_run_and_asks_a_person() -> None:
    """The graph must SUSPEND at the offer rather than deciding for the clinician."""
    _, _, state = _run_to_offer("stops")
    interrupts = state.get("__interrupt__")
    assert interrupts, "the run finished without asking anyone"
    payload = interrupts[0].value
    assert payload["kind"] == "sampling_offer"
    assert payload["answers"] == [ACCEPTED, DECLINED]
    # `is None`, not key-absence: `fit_node` now CLEARS the previous run's outcome keys to None
    # at the start of every run, so the key is present-and-None on a paused run. The property
    # that matters is unchanged — no view exists before the decision — but the earlier
    # membership form tested a fact about dict keys rather than that property, and it broke on
    # the very fix that made the clearing necessary.
    assert state.get("clinician_view") is None, (
        "a view was produced before the decision"
    )
    assert state.get("run_complete") is not True, (
        "the run claimed completeness while paused"
    )


def test_the_offer_leads_with_exposure_width_not_calibration() -> None:
    """Calibration rises in the forecast and falls when real points land.

    The card must therefore lead with the exposure interval. Asserted structurally — the
    calibration figures are permitted only under a key that names them as secondary — because
    the exact percentages move with the seed and pinning them would pin the wrong thing.
    """
    _, _, state = _run_to_offer("leads")
    payload = state["__interrupt__"][0].value
    assert "exposure_width_gain" in payload["expected_gain"]
    assert "calibration_now" not in payload["expected_gain"]
    assert "calibration_now" in payload["secondary_parameter_precision"]
    assert "NOT accuracy" in payload["secondary_parameter_precision"]["note"]


def test_the_offer_states_the_burden_in_draws() -> None:
    """A clinician weighing a request on a patient's behalf needs both halves."""
    _, _, state = _run_to_offer("burden")
    payload = state["__interrupt__"][0].value
    assert payload["burden"]["extra_draws"] == 3


def test_accepting_schedules_and_declining_flags() -> None:
    """Both answers must be reachable, and they must not produce the same outcome."""
    graph, config, _ = _run_to_offer("accept")
    accepted = graph.invoke(Command(resume={"decision": ACCEPTED}), config)
    view = accepted["clinician_view"]
    assert view.action is ClinicalAction.SCHEDULE_ADDITIONAL_PK_SAMPLE
    assert view.proposed_sampling is not None

    graph2, config2, _ = _run_to_offer("decline")
    declined = graph2.invoke(Command(resume={"decision": DECLINED}), config2)
    view2 = declined["clinician_view"]
    assert view2.action is ClinicalAction.FLAG_FOR_REVIEW
    assert view2.proposed_sampling is None


def test_an_unrecognised_decision_raises_rather_than_defaulting() -> None:
    """The default a fall-through would pick is `declined`, which SUPPRESSES the escalation.

    So there is no default. This is the mutation that matters on this node: a version that
    treats anything-not-accepted as a decline passes every other test in this file.
    """
    graph, config, _ = _run_to_offer("garbage")
    with pytest.raises(PkInputError, match="may only be"):
        graph.invoke(Command(resume={"decision": "maybe later"}), config)


def test_a_declined_offer_still_records_the_crossing() -> None:
    """Declining is a clinical choice, not an erasure of the finding."""
    graph, config, _ = _run_to_offer("still")
    declined = graph.invoke(Command(resume={"decision": DECLINED}), config)
    assert declined["clinician_view"].prediction.crosses_boundary is True


def test_every_per_run_state_key_is_cleared_at_the_start_of_a_run() -> None:
    """No key may carry one run's meaning into the next.

    THE FIRST VERSION OF THIS CLEAR WAS INCOMPLETE and a decorrelated verifier found it: six keys
    were cleared and `offer`, `prediction`, `action` and `exposure` were left standing, so a
    thread that ran a crossing case and then an in-range one ended with the new view beside the
    OLD offer and the OLD predicted interval. The list is now derived from the state's own
    annotations and checked at import; this test asserts the derivation covers the state and that
    `fit_node` actually writes every key the derivation names.
    """
    case = _fast_case()
    update = fit_node({"case": case})

    missing = PER_RUN_OUTCOME_KEYS - set(update)
    assert not missing, f"fit_node does not clear {sorted(missing)}"
    assert update["run_complete"] is False

    # The derivation must cover the state, not a remembered subset of it.
    inputs = {"case", "prior", "fit", "run_complete"}
    assert PER_RUN_OUTCOME_KEYS == set(PkAgentState.__annotations__) - inputs


def test_a_second_run_on_one_thread_carries_nothing_from_the_first() -> None:
    """The end-to-end form of the check above, over a real re-run on one thread.

    Run 1 crosses and is accepted, so it leaves an offer, an appointment and a completed view.
    Run 2 is the same patient with the sampling occasion already taken, so it takes a different
    path. Nothing from run 1 may still be sitting in the state that run 2 produces.
    """
    graph = build_graph()
    config = {"configurable": {"thread_id": "two-runs"}}
    graph.invoke({"case": _fast_case()}, config)
    first = dict(graph.invoke(Command(resume={"decision": ACCEPTED}), config))
    assert first["offer"] is not None
    assert first["appointment"] is not None
    first_prediction = first["prediction"]

    second_case = dataclasses.replace(
        load_demo_case(), offer_simulations=FAST_SIMULATIONS
    )
    second = dict(graph.invoke({"case": second_case}, config))

    # Whatever run 2 decided, no field may still hold run 1's answer.
    if second.get("__interrupt__"):
        assert second["clinician_view"] is None
        assert second["appointment"] is None
        assert second["run_complete"] is False
    assert second["prediction"] is not first_prediction, (
        "run 2 is reporting run 1's predicted interval"
    )


# ── Refusing to guess ────────────────────────────────────────────────────────


def test_a_degenerate_prediction_ends_the_run_instead_of_reaching_the_gate() -> None:
    """A failure to evaluate must never arrive at the gate as a missing prediction.

    Whatever the gate returned then would be a verdict nobody computed, and the value it would
    most plausibly return is `NO_ACTION` — indistinguishable on screen from a patient sitting
    comfortably in range.
    """
    assert (
        route_after_predict({"review_required": ReviewRequired("prediction", "why")})
        == "__end__"
    )
    assert route_after_predict({"prediction": object()}) == "gate"


def test_a_broken_care_plan_raises_rather_than_becoming_review_required() -> None:
    """A malformed bound is a defect in the plan, not thin data about the patient.

    Reporting it as "needs review" would file a broken configuration under the same heading as
    a patient whose record is genuinely hard to read.
    """
    with pytest.raises(PkInputError):
        CarePlan(
            lower_bound_ng_per_ml=10.0,
            upper_bound_ng_per_ml=5.0,
            plan_text_from_clinician="text",
            band_citation="cite",
        )


def test_predict_case_returns_review_required_rather_than_raising() -> None:
    """The degenerate path must be a VALUE, so a generic `except` cannot swallow it."""
    case = _fast_case()
    prior = prior_for(case.covariates)
    fit = fit_individual(case.doses, case.observations, prior)
    # A covariance large enough that the sampler cannot produce a usable interval.
    broken = dataclasses.replace(
        fit,
        covariance=tuple(
            tuple(1e6 if i == j else 0.0 for j in range(2)) for i in range(2)
        ),
    )
    outcome = predict_case(case, broken)
    assert isinstance(outcome, (ReviewRequired, Prediction))
    if isinstance(outcome, ReviewRequired):
        assert outcome.stage == "prediction"
        assert "not the same as a level inside" in outcome.reason


# ── Determinism ──────────────────────────────────────────────────────────────


def test_the_same_case_and_seeds_give_the_same_offer() -> None:
    """Re-running an evaluation must not move the numbers a clinician was shown."""
    _, _, first = _run_to_offer("det-a")
    _, _, second = _run_to_offer("det-b")
    assert (
        first["__interrupt__"][0].value["expected_gain"]
        == (second["__interrupt__"][0].value["expected_gain"])
    )


# ── The case type ────────────────────────────────────────────────────────────


def test_two_observations_at_one_instant_are_refused() -> None:
    """One instant cannot hold two different concentrations."""
    case = load_demo_case()
    with pytest.raises(PkInputError, match="share a time"):
        PatientCase(
            covariates=case.covariates,
            doses=case.doses,
            troughs=(Observation(time_h=10.0, concentration_ng_per_ml=5.0),),
            curve_samples=(Observation(time_h=10.0, concentration_ng_per_ml=9.0),),
            plan=case.plan,
            target_time_h=case.target_time_h,
            next_dose_time_h=case.next_dose_time_h,
            prediction_seed=1,
            offer_seed=2,
        )


def test_an_empty_dosing_history_is_refused() -> None:
    """An empty history would otherwise be fitted as a patient on no treatment."""
    case = load_demo_case()
    with pytest.raises(PkInputError, match="doses must not be empty"):
        PatientCase(
            covariates=case.covariates,
            doses=(),
            troughs=case.troughs,
            curve_samples=(),
            plan=case.plan,
            target_time_h=case.target_time_h,
            next_dose_time_h=case.next_dose_time_h,
            prediction_seed=1,
            offer_seed=2,
        )


def test_a_boolean_seed_is_refused() -> None:
    """`bool` subclasses `int`, so every later check passes for True and it becomes seed 1."""
    case = load_demo_case()
    with pytest.raises(PkInputError, match="prediction_seed must be an int"):
        PatientCase(
            covariates=case.covariates,
            doses=case.doses,
            troughs=case.troughs,
            curve_samples=(),
            plan=case.plan,
            target_time_h=case.target_time_h,
            next_dose_time_h=case.next_dose_time_h,
            prediction_seed=True,  # type: ignore[arg-type]
            offer_seed=2,
        )


def test_an_empty_plan_text_is_refused() -> None:
    """The patient channel has no prose of its own to fall back on."""
    with pytest.raises(PkInputError, match="plan_text_from_clinician"):
        CarePlan(
            lower_bound_ng_per_ml=5.0,
            upper_bound_ng_per_ml=10.0,
            plan_text_from_clinician="   ",
            band_citation="cite",
        )


def test_the_offer_node_never_asks_when_the_forecast_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed forecast degrades to a review flag; it does not become NO_ACTION.

    THE CROSSING THAT PRODUCED THE OFFER STILL STANDS. Only the estimate of what extra draws
    would buy has failed, so losing the forecast must not lose the finding — and `NO_ACTION` is
    what a caller catching the exception generically would produce.

    The failure is INJECTED at the boundary rather than provoked with a contrived case: the
    branch under test is this layer's handling of `CalibrationError`, not the numeric core's
    decision to raise one, and an input contrived to make the core raise would be testing the
    core's validation instead. An earlier version of this test tried that and SKIPPED, which
    left the branch uncovered while reading as a pass.
    """
    import agent_pk.agent.evaluate as evaluate_module

    def _refuse(*args: object, **kwargs: object) -> SamplingOffer:
        raise CalibrationError("no simulated future produced a usable fit")

    monkeypatch.setattr(evaluate_module, "build_sampling_offer", _refuse)

    case = _fast_case()
    prior = prior_for(case.covariates)
    fit = fit_individual(case.doses, case.observations, prior)
    update = offer_node({"case": case, "fit": fit, "prior": prior})

    assert update["action"] is ClinicalAction.FLAG_FOR_REVIEW
    assert update["action"] is not ClinicalAction.NO_ACTION
    assert "crossing itself stands" in update["offer_unavailable_reason"]
    assert "decision" not in update, (
        "a clinician was asked something with no data behind it"
    )


@pytest.mark.slow
def test_the_committed_demonstration_runs_at_its_own_settings() -> None:
    """The demo path, at the twenty-four futures every published figure was produced at.

    The fast tests above prove the STRUCTURE. This one proves the artifact actually shown on
    stage still runs, and that the two claims the pitch rests on hold at the real setting: the
    offer narrows the exposure interval, and it turns an estimate nothing can check into one
    the published equation can be run against.
    """
    _, _, state = _run_to_offer("committed", case=load_troughs_only_case())
    gain = state["__interrupt__"][0].value["expected_gain"]
    assert gain["exposure_width_gain"] > 0.0
    assert gain["independently_checkable_now"] is False
    assert gain["expected_independently_checkable"] is True


def test_doses_carry_through_to_the_prediction_window() -> None:
    """The scheduled dose must be in the history the prediction is made from.

    When it is not, every post-dose sample lands in the previous dose's tail and the forecast
    reads backwards — the defect that made a whole demo predict a fall it had invented.
    """
    case = _fast_case()
    latest_dose = max(dose.time_h for dose in case.doses)
    assert latest_dose <= case.target_time_h
    assert case.target_time_h - latest_dose < 24.0
    assert any(isinstance(dose, DoseEvent) for dose in case.doses)
