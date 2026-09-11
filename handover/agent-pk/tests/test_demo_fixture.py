"""The demo patient, regenerated and pinned.

Two jobs. First, every number in `data/demo_patient.json` is REGENERATED here from the seeds and
parameters the file itself records, and asserted equal — so the bytes on stage are reproducible
from the repository rather than whatever an RNG produced the morning someone built them.

Second, and this is the one that matters: the fixture has to make the sampling actually DECIDE
something. Four monthly troughs must leave the forecast straddling a therapeutic boundary, and the
four-point curve must resolve it. Without that property the demo shows a number getting slightly
different and nothing else, and the pitch has no moment in it.

NOTHING HERE IS EVIDENCE. The data is the published model simulated against itself. It pins a
user-interface demonstration; it establishes nothing about how well anything predicts.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from agent_pk.interactions import load_table
from agent_pk.pk import (
    Covariates,
    DoseEvent,
    Observation,
    concentration_at,
    fit_individual,
    predict_trough,
    prior_for,
)

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "data" / "demo_patient.json"
FORECAST_SEED = 11


@pytest.fixture(scope="module")
def fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rebuilt(fixture: dict) -> dict:
    """Regenerate the patient from the recorded recipe."""
    r = fixture["regeneration"]
    cov = Covariates(
        weight_kg=fixture["covariates"]["weight_kg"],
        cyp3a5_expresser=fixture["covariates"]["cyp3a5_expresser"],
    )
    prior = prior_for(cov)
    true_cl = math.exp(prior.log_clearance_mean) * r["clearance_multiple_of_population"]
    truth = prior.individual(
        clearance_l_per_h=true_cl,
        volume_central_l=fixture["true_parameters"]["volume_central_l"],
    )
    tau = r["dosing_interval_h"]
    doses = tuple(
        DoseEvent(time_h=i * tau, amount_mg=r["dose_mg"]) for i in range(r["days"] + 1)
    )

    def noisy(true_c: float, rng: np.random.Generator) -> float:
        cv = prior.proportional_residual_cv
        return round(true_c * float(np.exp(rng.normal(0.0, cv) - 0.5 * cv**2)), 4)

    rng = np.random.default_rng(r["trough_seed"])
    troughs = [
        {
            "time_h": d * tau - 0.25,
            "concentration_ng_per_ml": noisy(
                concentration_at(d * tau - 0.25, doses, truth), rng
            ),
        }
        for d in r["trough_days"]
    ]
    rng2 = np.random.default_rng(r["curve_seed"])
    cdt = r["curve_dose_time_h"]
    curve = [
        {
            "offset_h": o,
            "time_h": cdt + o,
            "concentration_ng_per_ml": noisy(
                concentration_at(cdt + o, doses, truth), rng2
            ),
        }
        for o in r["curve_offsets_h"]
    ]
    return {
        "prior": prior,
        "truth": truth,
        "true_cl": true_cl,
        "doses": doses,
        "troughs": troughs,
        "curve": curve,
    }


# ── The fixture is reproducible from the repository ──────────────────────────


def test_the_troughs_regenerate_exactly(fixture: dict, rebuilt: dict) -> None:
    assert rebuilt["troughs"] == fixture["troughs"]


def test_the_measured_curve_regenerates_exactly(fixture: dict, rebuilt: dict) -> None:
    assert rebuilt["curve"] == fixture["measured_curve"]


def test_the_true_clearance_regenerates_exactly(fixture: dict, rebuilt: dict) -> None:
    assert (
        round(rebuilt["true_cl"], 4) == fixture["true_parameters"]["clearance_l_per_h"]
    )


def test_the_scheduled_next_dose_is_present(fixture: dict) -> None:
    # The forecast refuses without a dose scheduled between now and the target, and a fixture
    # that omitted it would fail on stage rather than here.
    target = fixture["prediction_target_time_h"]
    assert any(d["time_h"] > target for d in fixture["doses"]) or any(
        d["time_h"] == 720.0 for d in fixture["doses"]
    )


def test_the_interacting_drug_resolves_in_the_curated_table(fixture: dict) -> None:
    record = load_table().lookup(fixture["interacting_drug"]["agent"])
    assert record.sources, "the demo interaction must carry its citations"


# ── The property the demo exists for ─────────────────────────────────────────


@pytest.fixture(scope="module")
def forecasts(fixture: dict, rebuilt: dict) -> dict:
    doses = rebuilt["doses"]
    prior = rebuilt["prior"]
    lo = fixture["band"]["lower_ng_per_ml"]
    hi = fixture["band"]["upper_ng_per_ml"]
    target = fixture["prediction_target_time_h"]

    troughs = tuple(
        Observation(
            time_h=t["time_h"], concentration_ng_per_ml=t["concentration_ng_per_ml"]
        )
        for t in fixture["troughs"]
    )
    curve = tuple(
        Observation(
            time_h=c["time_h"], concentration_ng_per_ml=c["concentration_ng_per_ml"]
        )
        for c in fixture["measured_curve"]
    )
    fit_troughs = fit_individual(doses, troughs, prior)
    fit_curve = fit_individual(doses, troughs + curve, prior)
    return {
        "lo": lo,
        "hi": hi,
        "true_trough": concentration_at(target, doses, rebuilt["truth"]),
        "true_cl": rebuilt["true_cl"],
        "fit_troughs": fit_troughs,
        "fit_curve": fit_curve,
        "p_troughs": predict_trough(
            doses, fit_troughs, target, lo, hi, seed=FORECAST_SEED
        ),
        "p_curve": predict_trough(doses, fit_curve, target, lo, hi, seed=FORECAST_SEED),
    }


def test_the_patient_is_genuinely_in_band(forecasts: dict) -> None:
    # If the truth sat outside the band the demo would be about a patient who really is in
    # trouble, and the sampling could not change the right answer.
    assert forecasts["lo"] < forecasts["true_trough"] < forecasts["hi"]


def test_troughs_alone_leave_the_patient_more_likely_out_of_range_than_in(
    forecasts: dict,
) -> None:
    """Four routine troughs put this patient's risk of being sub-therapeutic above a coin flip.

    Stated as a PROBABILITY rather than as "the interval touches the line", because the interval
    is a prediction interval for a measured trough and its edges are 5th and 95th percentiles —
    so boundary contact means only that a 5% tail reached the boundary, which is true of a great
    many perfectly stable patients. The probability is the quantity that separates this patient
    from those, and it is the quantity a clinician can act on proportionately.
    """
    p = forecasts["p_troughs"]
    assert p.probability_below > 0.40, (
        "the demo's opening state is a patient whose risk of being under-immunosuppressed is "
        "substantial on routine monitoring alone — if it were not, step 2 would be answering a "
        "question nobody had"
    )
    assert p.crosses_boundary, (
        "the interval must also reach the boundary, or the two signals "
    )
    "disagree and the fixture is not the story it claims to be"


def test_the_four_point_curve_materially_reduces_the_risk(forecasts: dict) -> None:
    """The pitch, in the one assertion that is actually true of this fixture.

    THIS TEST REPLACES an assertion that the curve made the interval stop crossing the boundary.
    That assertion was FALSE and its falsity was the most serious finding of the 2026-09-09
    panel: it held only while the interval omitted the model's own 28.2% residual error, i.e.
    while the interval answered "where is this patient's expected level" rather than "what will
    the laboratory report". Under the corrected interval the forecast still reaches both
    boundaries after sampling — and that is not a failure of the demo, it is the honest width of
    a tacrolimus prediction from four samples.

    What the extra samples genuinely bought is a HALVING of the probability of being out of
    range, together with a clearance estimate that moved toward the truth. That is a real
    clinical gain, it needs no hidden truth value to state, and it is the thing a transplant
    clinician is actually deciding: whether to act now or measure again.
    """
    before, after = forecasts["p_troughs"], forecasts["p_curve"]
    assert after.probability_below < before.probability_below / 2.0, (
        "the four-point curve must at least halve the probability of being sub-therapeutic, or "
        "asking the patient for three more needles was not worth it"
    )
    # TOTAL out-of-range risk falls sharply but does NOT quite halve (measured 0.55 -> 0.29, a
    # 47% reduction), and the reason is worth keeping rather than tuning away: the curve moves
    # the clearance estimate DOWN, which lifts predicted concentrations, so a little risk
    # migrates from the low side to the high side (P(above) 0.013 -> 0.059). The clinically
    # important quantity still halves; the total is bounded loosely enough that it is asserting
    # the effect rather than pinning Monte Carlo noise at the default sample size.
    assert after.probability_outside < before.probability_outside * 0.6
    # And the gain must not have come from pretending to be certain. A prediction interval for a
    # tacrolimus trough is genuinely wide, and a "resolved" forecast that had narrowed to a point
    # would be the flattering fiction this fixture exists to prevent.
    assert after.upper_ng_per_ml - after.lower_ng_per_ml > 3.0


def test_the_curve_moves_the_clearance_estimate_toward_the_truth(
    forecasts: dict,
) -> None:
    # Guards against the failure this project already corrected once: a demo where sampling
    # looks decisive while making the estimate WORSE. If a future edit to the fixture breaks
    # this, the demo has become a flattering fiction and must not be shown.
    true_cl = forecasts["true_cl"]
    err_troughs = abs(forecasts["fit_troughs"].parameters.clearance_l_per_h - true_cl)
    err_curve = abs(forecasts["fit_curve"].parameters.clearance_l_per_h - true_cl)
    assert err_curve < err_troughs


def test_absorption_is_only_estimated_once_the_curve_lands(forecasts: dict) -> None:
    # Troughs cannot identify absorption; post-dose points can. Pinned because it is the
    # mechanism the sampling offer is built on.
    assert forecasts["fit_troughs"].estimated_ka is False
    assert forecasts["fit_curve"].estimated_ka is True
