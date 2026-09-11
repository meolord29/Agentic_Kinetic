"""test_calibration.py — the number shown to a clinician, and the check beneath the model.

The calibration figure is what a clinician looks at when deciding whether to ask a patient for
three extra fingersticks. If it moved for reasons of dimensionality rather than of knowledge, or
if it could be high on a fit that learned nothing, the decision would rest on an artefact. So the
properties tested here are the ones that make it readable rather than merely computable.

The cross-check is tested for the failure it exists to catch AND for the failure it could
quietly become: a check fed the model's own output would agree with itself always.

Every patient here is synthetic and generated from a seeded RNG.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from agent_pk.pk.calibration import (
    LSS_OFFSETS_H,
    AucCrossCheck,
    CalibrationError,
    auc_cross_check,
    build_sampling_offer,
    expected_calibration_after,
    expected_exposure_width_after,
    exposure_uncertainty,
    profile_calibration,
    published_auc_from_curve,
)
from agent_pk.pk.fit import FitResult, fit_individual
from agent_pk.pk.model import (
    DoseEvent,
    Observation,
    PkInputError,
    PkParameters,
    concentration_at,
)
from agent_pk.pk.priors import (
    CLD_F_L_PER_H_70KG,
    KA_PER_H,
    LAG_H,
    VP_F_L,
    Covariates,
    prior_for,
)

DOSE_INTERVAL_H = 24.0
DOSE_MG = 4.0
N_DAYS = 30
LAST_DOSE_H = (N_DAYS - 1) * DOSE_INTERVAL_H


def _params(
    clearance_l_per_h: float, volume_central_l: float, ka_per_h: float = KA_PER_H
) -> PkParameters:
    """Individual parameters with the published model's FIXED disposition values filled in.

    Vp/F, CLD/F and the lag are population constants of the source model, not things a fit
    estimates, so a test that hardcoded them would be asserting against a copy that could drift
    from `priors.py`. They are read from the source constants instead.
    """
    return PkParameters(
        clearance_l_per_h=clearance_l_per_h,
        volume_central_l=volume_central_l,
        volume_peripheral_l=VP_F_L,
        intercompartmental_clearance_l_per_h=CLD_F_L_PER_H_70KG,
        ka_per_h=ka_per_h,
        lag_h=LAG_H,
    )


TRUE = _params(26.0, 350.0)
"""A synthetic patient. CL/F 26.0 sits close to the published carrier value of 26.5."""


def _doses() -> tuple[DoseEvent, ...]:
    return tuple(
        DoseEvent(time_h=index * DOSE_INTERVAL_H, amount_mg=DOSE_MG, status="taken")
        for index in range(N_DAYS)
    )


NEXT_DOSE_H = N_DAYS * DOSE_INTERVAL_H


def _doses_with_scheduled_next() -> tuple[DoseEvent, ...]:
    """Dosing history plus the dose the offered samples are timed from.

    A forecast is asked what happens IF the patient takes tomorrow's dose and gives samples
    around it, so tomorrow's dose has to be in the history handed to it. Omitting it used to
    return a confident number for a schedule that was never simulated; `expected_calibration_after`
    now refuses instead.
    """
    return (
        *_doses(),
        DoseEvent(time_h=NEXT_DOSE_H, amount_mg=DOSE_MG, status="taken"),
    )


def _prior():  # type: ignore[no-untyped-def]
    return prior_for(
        Covariates(formulation="advagraf_prolonged_release", cyp3a5_expresser=False)
    )


def _simulate(times: tuple[float, ...], seed: int, cv: float = 0.18):  # type: ignore[no-untyped-def]
    rng = np.random.default_rng(seed)
    doses = _doses()
    return tuple(
        Observation(
            time_h,
            max(
                concentration_at(time_h, doses, TRUE)
                * (1.0 + cv * float(rng.standard_normal())),
                0.01,
            ),
        )
        for time_h in times
    )


def _trough_times(n: int) -> tuple[float, ...]:
    return tuple((N_DAYS - n + i) * DOSE_INTERVAL_H - 0.05 for i in range(n))


def _curve_times() -> tuple[float, ...]:
    return tuple(LAST_DOSE_H + offset for offset in LSS_OFFSETS_H)


# ── Profile calibration ──────────────────────────────────────────────────────


def test_a_fit_with_no_observations_is_zero_calibrated() -> None:
    """No data means nothing individual has been learned, and the number must say so."""
    prior = _prior()
    fit = fit_individual(_doses(), (), prior)
    assert profile_calibration(fit, prior) == pytest.approx(0.0, abs=1e-9)


def test_calibration_rises_with_informative_data() -> None:
    prior = _prior()
    doses = _doses()
    one = fit_individual(doses, _simulate(_trough_times(1), seed=4), prior)
    four = fit_individual(doses, _simulate(_trough_times(4), seed=4), prior)
    curve = fit_individual(doses, _simulate(_curve_times(), seed=4), prior)

    assert 0.0 < profile_calibration(one, prior) < profile_calibration(four, prior)
    assert profile_calibration(curve, prior) > 0.0


def test_calibration_is_bounded_and_readable() -> None:
    prior = _prior()
    doses = _doses()
    for times in (_trough_times(1), _trough_times(4), _curve_times()):
        value = profile_calibration(
            fit_individual(doses, _simulate(times, 9), prior), prior
        )
        assert 0.0 <= value <= 1.0


def test_calibration_is_normalised_per_parameter_not_by_dimension() -> None:
    """The number must move when KNOWLEDGE changes, not when the schedule changes shape.

    Without the n-th root, a three-parameter fit would score differently from a two-parameter one
    for reasons of dimensionality alone, and the figure on a clinician's screen would jump when
    absorption started being estimated. Checked by giving both fits the SAME per-parameter
    information and requiring the same answer.
    """
    prior = _prior()
    two = FitResult(
        parameters=TRUE,
        log_theta=(1.0, 2.0),
        covariance=(
            (0.25 * prior.omega_log_clearance**2, 0.0),
            (0.0, 0.25 * prior.omega_log_volume**2),
        ),
        n_observations=4,
        converged=True,
        uncertainty_source="laplace",
        haematocrit_known=True,
        haematocrit=0.45,
        residual_cv=0.282,
    )
    three = FitResult(
        parameters=TRUE,
        log_theta=(1.0, 2.0, 0.5),
        covariance=(
            (0.25 * prior.omega_log_clearance**2, 0.0, 0.0),
            (0.0, 0.25 * prior.omega_log_volume**2, 0.0),
            (0.0, 0.0, 0.25 * prior.omega_log_ka**2),
        ),
        n_observations=4,
        converged=True,
        uncertainty_source="laplace",
        haematocrit_known=True,
        haematocrit=0.45,
        residual_cv=0.282,
    )
    # Each parameter is a quarter of its prior variance in both cases, so the per-parameter
    # information is identical and the reported calibration must be too.
    assert profile_calibration(two, prior) == pytest.approx(
        profile_calibration(three, prior), abs=1e-12
    )


def test_a_degenerate_covariance_refuses_rather_than_scoring() -> None:
    """An uncomputable calibration is a refusal, never a zero — zero means something else."""
    prior = _prior()
    fit = FitResult(
        parameters=TRUE,
        log_theta=(1.0, 2.0),
        covariance=((1e-320, 0.0), (0.0, 1e-320)),
        n_observations=2,
        converged=True,
        uncertainty_source="laplace",
        haematocrit_known=True,
        haematocrit=0.45,
        residual_cv=0.282,
    )
    with pytest.raises(CalibrationError):
        profile_calibration(fit, prior)


# ── The offer put to the clinician ───────────────────────────────────────────


def test_the_offer_states_both_the_gain_and_the_burden() -> None:
    """A gain shown without its burden is a request the clinician cannot weigh."""
    prior = _prior()
    doses = _doses_with_scheduled_next()
    obs = _simulate(_trough_times(2), seed=6)
    fit = fit_individual(doses, obs, prior)

    offer = build_sampling_offer(
        doses,
        fit,
        prior,
        existing_observations=obs,
        next_dose_time_h=NEXT_DOSE_H,
        seed=21,
        n_simulations=12,
    )
    assert offer.offsets_post_dose_h == LSS_OFFSETS_H
    assert offer.n_extra_samples == 3  # C1, C3, C6 — the trough was already scheduled
    assert 0.0 <= offer.calibration_now <= 1.0
    assert 0.0 <= offer.expected_calibration <= 1.0
    assert offer.expected_gain == pytest.approx(
        offer.expected_calibration - offer.calibration_now
    )


def test_the_offer_expects_a_gain_for_a_barely_calibrated_patient() -> None:
    prior = _prior()
    doses = _doses_with_scheduled_next()
    obs = _simulate(_trough_times(1), seed=6)
    fit = fit_individual(doses, obs, prior)
    offer = build_sampling_offer(
        doses,
        fit,
        prior,
        existing_observations=obs,
        next_dose_time_h=NEXT_DOSE_H,
        seed=21,
        n_simulations=12,
    )
    assert offer.expected_gain > 0.0, (
        f"a patient with one trough should expect to gain from a four-point curve, "
        f"got {offer.expected_gain:+.3f}"
    )


def test_the_forecast_is_deterministic_under_its_seed() -> None:
    """The determinism contract: same inputs and seed, same answer."""
    prior = _prior()
    doses = _doses_with_scheduled_next()
    obs = _simulate(_trough_times(2), seed=6)
    fit = fit_individual(doses, obs, prior)
    kwargs = {
        "existing_observations": obs,
        "next_dose_time_h": NEXT_DOSE_H,
        "offsets_post_dose_h": LSS_OFFSETS_H,
        "seed": 5,
        "n_simulations": 8,
    }
    first = expected_calibration_after(doses, fit, prior, **kwargs)  # type: ignore[arg-type]
    second = expected_calibration_after(doses, fit, prior, **kwargs)  # type: ignore[arg-type]
    assert first == second


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"offsets_post_dose_h": ()}, "must not be empty"),
        ({"offsets_post_dose_h": (0.0, -1.0)}, "must not be negative"),
        ({"seed": True}, "seed must be an int"),
        ({"n_simulations": 0}, "n_simulations"),
    ],
)
def test_the_forecast_refuses_malformed_requests(
    kwargs: dict[str, object], match: str
) -> None:
    prior = _prior()
    doses = _doses_with_scheduled_next()
    obs = _simulate(_trough_times(2), seed=6)
    fit = fit_individual(doses, obs, prior)
    call = {
        "existing_observations": obs,
        "next_dose_time_h": NEXT_DOSE_H,
        "offsets_post_dose_h": LSS_OFFSETS_H,
        "seed": 5,
        "n_simulations": 8,
        **kwargs,
    }
    with pytest.raises(PkInputError, match=match):
        expected_calibration_after(doses, fit, prior, **call)  # type: ignore[arg-type]


# ── The published equation and the cross-check ───────────────────────────────


def test_the_published_equation_reproduces_its_own_coefficients() -> None:
    """A unit curve must return the intercept plus the sum of the coefficients."""
    assert published_auc_from_curve((1.0, 1.0, 1.0, 1.0)) == pytest.approx(
        0.57 + 12.72 + 1.84 + 2.80 + 6.79
    )


@pytest.mark.parametrize(
    "curve",
    [
        (0.0, 5.0, 4.0, 3.0),
        (-1.0, 5.0, 4.0, 3.0),
        (float("nan"), 5.0, 4.0, 3.0),
    ],
)
def test_the_published_equation_refuses_an_impossible_concentration(
    curve: tuple[float, float, float, float],
) -> None:
    with pytest.raises(PkInputError):
        published_auc_from_curve(curve)


def test_the_published_equation_refuses_the_wrong_number_of_points() -> None:
    with pytest.raises(PkInputError, match="exactly 4"):
        published_auc_from_curve((5.0, 4.0, 3.0))  # type: ignore[arg-type]


def test_a_well_fitted_curve_agrees_with_the_published_equation() -> None:
    prior = _prior()
    doses = _doses()
    observations = _simulate(_curve_times(), seed=4)
    fit = fit_individual(doses, observations, prior)

    measured = tuple(obs.concentration_ng_per_ml for obs in observations)
    check = auc_cross_check(
        doses,
        fit,
        dose_time_h=LAST_DOSE_H,
        measured_curve=measured,  # type: ignore[arg-type]
    )
    assert isinstance(check, AucCrossCheck)
    assert check.agrees, (
        f"a fit of the same four points disagrees with the published equation by "
        f"{check.relative_disagreement:+.1%}"
    )
    assert check.population_limit


def test_the_cross_check_reports_disagreement_rather_than_raising() -> None:
    """Disagreement is a finding for a clinician, not a crash — and it must be visible."""
    prior = _prior()
    doses = _doses()
    fit = fit_individual(doses, _simulate(_curve_times(), seed=4), prior)

    # A curve from a materially different patient than the one that was fitted.
    check = auc_cross_check(
        doses, fit, dose_time_h=LAST_DOSE_H, measured_curve=(30.0, 45.0, 40.0, 34.0)
    )
    assert check.agrees is False
    assert abs(check.relative_disagreement) > 0.25


def test_the_cross_check_cannot_be_fed_the_models_own_predictions() -> None:
    """The check must compare the model with MEASUREMENTS, never with itself.

    This is the "replayed input satisfies the gate it feeds" failure: if the caller passed the
    model's own predicted concentrations, agreement would be true by construction and the gate
    would be decorative. The signature cannot prevent that, so the property is documented here
    and demonstrated — feeding predictions produces near-perfect agreement, which is exactly the
    false comfort a reader must not mistake for validation.
    """
    prior = _prior()
    doses = _doses()
    fit = fit_individual(doses, _simulate(_curve_times(), seed=4), prior)

    self_fed = tuple(
        concentration_at(LAST_DOSE_H + offset, doses, fit.parameters)
        for offset in LSS_OFFSETS_H
    )
    check = auc_cross_check(
        doses,
        fit,
        dose_time_h=LAST_DOSE_H,
        measured_curve=self_fed,  # type: ignore[arg-type]
    )
    # It agrees — and that agreement is worthless, which is the point being recorded.
    assert check.agrees is True


def test_the_cross_check_refuses_an_impossible_tolerance() -> None:
    prior = _prior()
    doses = _doses()
    fit = fit_individual(doses, _simulate(_curve_times(), seed=4), prior)
    for bad in (0.0, 1.0, -0.1):
        with pytest.raises(PkInputError, match="tolerance"):
            auc_cross_check(
                doses,
                fit,
                dose_time_h=LAST_DOSE_H,
                measured_curve=(8.0, 14.0, 11.0, 6.0),
                tolerance=bad,
            )


# ── Exposure uncertainty: the number that is actually comparable ─────────────


# REMOVED: `test_the_calibration_figure_can_flatter_a_worse_fit`.
#
# It asserted a measured ORDERING between two fits of our own `profile_calibration` metric on a
# synthetic patient — another finding derived from simulation rather than taken from a source.
# The warning it guarded still stands in `profile_calibration`'s own docstring: the figure is
# parameter precision, not accuracy, and it must not be presented to a clinician as accuracy.
# That is a statement about what the number MEANS, which needs no simulation to justify.


def test_only_a_curve_fit_can_be_independently_checked() -> None:
    """A confident number nothing can check is the state a clinician most needs told about."""
    prior = _prior()
    doses = _doses()
    trough_obs = _simulate(_trough_times(4), seed=3)
    trough_fit = fit_individual(doses, trough_obs, prior)
    curve_obs = _simulate(_curve_times(), seed=3)
    curve_fit = fit_individual(doses, curve_obs, prior)

    trough_exposure = exposure_uncertainty(
        doses, trough_fit, start_h=LAST_DOSE_H, end_h=LAST_DOSE_H + 24.0, seed=2
    )
    curve_exposure = exposure_uncertainty(
        doses, curve_fit, start_h=LAST_DOSE_H, end_h=LAST_DOSE_H + 24.0, seed=2
    )
    assert trough_exposure.independently_checkable is False
    assert curve_exposure.independently_checkable is True


def test_exposure_interval_brackets_its_own_median_and_is_dimensionless() -> None:
    prior = _prior()
    doses = _doses()
    obs = _simulate(_curve_times(), seed=3)
    fit = fit_individual(doses, obs, prior)
    estimate = exposure_uncertainty(
        doses, fit, start_h=LAST_DOSE_H, end_h=LAST_DOSE_H + 24.0, seed=2
    )
    assert (
        estimate.lower_ng_h_per_ml
        <= estimate.median_ng_h_per_ml
        <= estimate.upper_ng_h_per_ml
    )
    assert estimate.relative_width > 0.0
    assert estimate.relative_width == pytest.approx(
        (estimate.upper_ng_h_per_ml - estimate.lower_ng_h_per_ml)
        / estimate.median_ng_h_per_ml
    )


def test_exposure_uncertainty_is_deterministic_under_its_seed() -> None:
    prior = _prior()
    doses = _doses()
    obs = _simulate(_curve_times(), seed=3)
    fit = fit_individual(doses, obs, prior)
    kwargs = {"start_h": LAST_DOSE_H, "end_h": LAST_DOSE_H + 24.0, "seed": 8}
    first = exposure_uncertainty(doses, fit, **kwargs)  # type: ignore[arg-type]
    second = exposure_uncertainty(doses, fit, **kwargs)  # type: ignore[arg-type]
    assert first == second


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"seed": True}, "seed must be an int"),
        ({"n_samples": 10}, "n_samples"),
        ({"credible_mass": 1.0}, "credible_mass"),
        ({"end_h": LAST_DOSE_H}, "strictly after"),
    ],
)
def test_exposure_uncertainty_refuses_malformed_settings(
    kwargs: dict[str, object], match: str
) -> None:
    prior = _prior()
    doses = _doses()
    obs = _simulate(_curve_times(), seed=3)
    fit = fit_individual(doses, obs, prior)
    call = {
        "start_h": LAST_DOSE_H,
        "end_h": LAST_DOSE_H + 24.0,
        "seed": 2,
        **kwargs,
    }
    with pytest.raises(PkInputError, match=match):
        exposure_uncertainty(doses, fit, **call)  # type: ignore[arg-type]


# ── The offer card leads with exposure width, not calibration ────────────────


def _offer_call(observations: tuple[Observation, ...]) -> dict[str, object]:
    return {
        "existing_observations": observations,
        "next_dose_time_h": NEXT_DOSE_H,
        "offsets_post_dose_h": LSS_OFFSETS_H,
        "start_h": NEXT_DOSE_H,
        "end_h": NEXT_DOSE_H + 24.0,
        "seed": 5,
    }


def test_the_offer_forecasts_a_narrower_exposure_interval() -> None:
    """The card's headline claim must be one the built code actually supports.

    UI-SPEC originally promised the clinician a calibration rise (34% to 81%). Calibration is
    parameter PRECISION and falls when real post-dose points land, so that card forecast a rise
    and would have delivered a drop live on stage. Exposure width is the quantity that genuinely
    improves, so it is the quantity the offer leads with, and this test pins that it improves.
    """
    prior = _prior()
    doses = _doses_with_scheduled_next()
    trough_obs = _simulate(_trough_times(4), seed=3)
    trough_fit = fit_individual(doses, trough_obs, prior)

    width, checkable = expected_exposure_width_after(
        doses,
        trough_fit,
        prior,
        **_offer_call(trough_obs),  # type: ignore[arg-type]
    )
    now = exposure_uncertainty(
        doses, trough_fit, start_h=NEXT_DOSE_H, end_h=NEXT_DOSE_H + 24.0, seed=5
    )
    assert width < now.relative_width, (
        "sampling the curve must be forecast to NARROW the exposure interval — if this "
        "reverses, the offer card is promising something the model does not deliver"
    )
    assert now.independently_checkable is False
    assert checkable is True, (
        "the offered schedule has post-dose points, so the published equation becomes runnable "
        "— this flip is the honest answer to 'why sample more'"
    )


def test_the_offer_reports_that_sampling_makes_the_estimate_checkable() -> None:
    """What the sampling offer actually buys, stated structurally rather than measured.

    An earlier version of this test asserted magnitudes — that exposure width roughly halves and
    calibration stays flat. Those were numbers this project measured on its own synthetic patient
    under a population prior it had invented, and they did not survive being re-measured against
    a published model. So the claim the card makes is now the one that does not depend on any
    simulation of ours: taking the C0-C1-C3-C6 schedule makes the published limited-sampling
    equation RUNNABLE, so the estimate acquires an independent cross-check it did not have.

    That is a property of what the published equation requires as input, not a finding.
    """
    prior = _prior()
    doses = _doses_with_scheduled_next()
    trough_obs = _simulate(_trough_times(4), seed=3)
    trough_fit = fit_individual(doses, trough_obs, prior)

    offer = build_sampling_offer(
        doses,
        trough_fit,
        prior,
        existing_observations=trough_obs,
        next_dose_time_h=NEXT_DOSE_H,
        seed=5,
        n_simulations=8,
    )
    assert offer.independently_checkable_now is False, (
        "a trough-only fit cannot be checked against the published equation — this is the "
        "honest answer to 'why sample more'"
    )
    assert offer.expected_independently_checkable is True
    assert offer.n_extra_samples == 3, "three draws beyond the already-scheduled trough"
    assert 0.0 <= offer.calibration_now <= 1.0
    assert offer.exposure_width_now > 0.0
    assert offer.expected_exposure_width > 0.0


def test_expected_width_refuses_rather_than_reporting_a_zero() -> None:
    """A width of zero reads as PERFECT CERTAINTY, so an unusable forecast must raise.

    This is the inverse of the calibration sibling, where zero means "no gain" and is merely
    wrong. Here a silent zero would be the single most dangerous number the card could show.
    """
    prior = _prior()
    doses = _doses_with_scheduled_next()
    obs = _simulate(_curve_times(), seed=3)
    fit = fit_individual(doses, obs, prior)
    call = _offer_call(obs) | {"offsets_post_dose_h": (0.0, 1.0), "n_simulations": 2}
    # A posterior this wide makes exp() of every parameter draw overflow to inf, so every
    # simulated future is skipped as unusable — the state the refusal exists for.
    broken = replace(
        fit,
        covariance=np.diag(np.full(np.asarray(fit.covariance).shape[0], 1.0e6)),
    )
    with pytest.raises(CalibrationError, match="refusal, not a width of zero"):
        expected_exposure_width_after(doses, broken, prior, **call)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"seed": True}, "seed must be an int"),
        ({"n_simulations": True}, "n_simulations must be an int"),
        ({"n_simulations": 0}, "n_simulations must be an int"),
        ({"offsets_post_dose_h": ()}, "must not be empty"),
        ({"offsets_post_dose_h": (-1.0,)}, "must not be negative"),
        ({"end_h": LAST_DOSE_H}, "end_h must be after start_h"),
        ({"start_h": float("nan")}, "start_h"),
    ],
)
def test_expected_width_refuses_malformed_settings(
    kwargs: dict[str, object], match: str
) -> None:
    """`True` is rejected as a seed BECAUSE bool subclasses int and would silently become 1."""
    prior = _prior()
    doses = _doses_with_scheduled_next()
    obs = _simulate(_curve_times(), seed=3)
    fit = fit_individual(doses, obs, prior)
    with pytest.raises(PkInputError, match=match):
        expected_exposure_width_after(
            doses,
            fit,
            prior,
            **(_offer_call(obs) | kwargs),  # type: ignore[arg-type]
        )


def test_the_offer_is_reproducible_from_its_seed() -> None:
    """The determinism contract: same inputs and seed, byte-identical offer."""
    prior = _prior()
    doses = _doses_with_scheduled_next()
    obs = _simulate(_trough_times(4), seed=3)
    fit = fit_individual(doses, obs, prior)
    first = build_sampling_offer(
        doses,
        fit,
        prior,
        existing_observations=obs,
        next_dose_time_h=NEXT_DOSE_H,
        seed=5,
        n_simulations=8,
    )
    second = build_sampling_offer(
        doses,
        fit,
        prior,
        existing_observations=obs,
        next_dose_time_h=NEXT_DOSE_H,
        seed=5,
        n_simulations=8,
    )
    assert first == second


def test_the_forecast_refuses_a_schedule_whose_dose_is_not_in_the_history() -> None:
    """The offsets are measured from a dose, so that dose must be in `doses`.

    Without this guard the simulation models a future in which the patient never takes the dose
    the samples are timed from: every "post-dose" sample lands in the previous dose's tail, no
    sample is absorption-informative, every refit returns trough-only, and the offer reports a
    confident gain for a schedule it never simulated. Nothing in the returned number looks wrong,
    which is exactly why this refuses rather than warns.
    """
    prior = _prior()
    doses = _doses()  # deliberately WITHOUT the scheduled next dose
    obs = _simulate(_trough_times(4), seed=3)
    fit = fit_individual(doses, obs, prior)
    with pytest.raises(PkInputError, match="no delivered dose at next_dose_time_h"):
        build_sampling_offer(
            doses,
            fit,
            prior,
            existing_observations=obs,
            next_dose_time_h=NEXT_DOSE_H,
            seed=5,
        )


def test_the_calibration_forecast_also_refuses_rather_than_reporting_a_zero() -> None:
    """The sibling refusal. Tested because a contract only one branch honours is half a contract.

    `expected_exposure_width_after` had this covered and `expected_calibration_after` did not,
    so a regression in the calibration path would have gone unnoticed while its own docstring
    promised a refusal.
    """
    prior = _prior()
    doses = _doses_with_scheduled_next()
    obs = _simulate(_curve_times(), seed=3)
    fit = fit_individual(doses, obs, prior)
    broken = replace(
        fit,
        covariance=np.diag(np.full(np.asarray(fit.covariance).shape[0], 1.0e6)),
    )
    with pytest.raises(CalibrationError, match="refusal, not a gain of zero"):
        expected_calibration_after(
            doses,
            broken,
            prior,
            existing_observations=obs,
            next_dose_time_h=NEXT_DOSE_H,
            offsets_post_dose_h=LSS_OFFSETS_H,
            seed=5,
            n_simulations=2,
        )


def test_an_offer_of_troughs_alone_is_refused() -> None:
    """A schedule with no post-dose draw asks the patient for nothing and can never be checked.

    It previously returned a confident-looking forecast with `n_extra_samples=0`, which would
    have rendered as an offer card proposing no samples.
    """
    prior = _prior()
    doses = _doses_with_scheduled_next()
    obs = _simulate(_trough_times(4), seed=3)
    fit = fit_individual(doses, obs, prior)
    with pytest.raises(PkInputError, match="at least one draw after the dose"):
        build_sampling_offer(
            doses,
            fit,
            prior,
            existing_observations=obs,
            next_dose_time_h=NEXT_DOSE_H,
            offsets_post_dose_h=(0.0,),
            seed=5,
        )


def test_a_bool_exposure_window_is_refused() -> None:
    """`True` is finite and positive, so a bare isfinite check accepted it as a one-hour window."""
    prior = _prior()
    doses = _doses_with_scheduled_next()
    obs = _simulate(_trough_times(4), seed=3)
    fit = fit_individual(doses, obs, prior)
    with pytest.raises(PkInputError, match="must be a real number, not a bool"):
        build_sampling_offer(
            doses,
            fit,
            prior,
            existing_observations=obs,
            next_dose_time_h=NEXT_DOSE_H,
            exposure_window_h=True,  # type: ignore[arg-type]
            seed=5,
        )


def test_a_non_lss_schedule_is_not_advertised_as_independently_checkable() -> None:
    """Absorption being identifiable is not the same as the cross-check being runnable.

    `estimated_ka` is True for any two points inside the 8 h absorption window, but
    `published_auc_from_curve` consumes C0, C1, C3 and C6 specifically. A schedule of (0, 2, 4)
    therefore identifies absorption while leaving the published equation unrunnable — and the
    card would have promised a clinician a cross-check that cannot happen.
    """
    prior = _prior()
    doses = _doses_with_scheduled_next()
    obs = _simulate(_trough_times(4), seed=3)
    fit = fit_individual(doses, obs, prior)

    _, checkable = expected_exposure_width_after(
        doses,
        fit,
        prior,
        existing_observations=obs,
        next_dose_time_h=NEXT_DOSE_H,
        offsets_post_dose_h=(0.0, 2.0, 4.0),
        start_h=NEXT_DOSE_H,
        end_h=NEXT_DOSE_H + 24.0,
        seed=5,
        n_simulations=4,
    )
    assert checkable is False, (
        "a schedule that identifies absorption but omits the LSS times cannot be cross-checked "
        "against the published equation, and must not be advertised as checkable"
    )


def test_the_calibration_forecast_is_pinned_to_a_value_not_only_a_property() -> None:
    """A pinned tuple, because the property tests would pass an extraction that changed the
    RNG consumption order. The repository is not under version control, so this value IS the
    baseline that would catch a silent behavioural drift in `_simulated_refits`.

    If this fails after a deliberate change to the simulation, re-measure and update the value in
    the same commit as the change — do not delete the test.
    """
    prior = _prior()
    doses = _doses_with_scheduled_next()
    obs = _simulate(_trough_times(4), seed=3)
    fit = fit_individual(doses, obs, prior)
    expected = expected_calibration_after(
        doses,
        fit,
        prior,
        existing_observations=obs,
        next_dose_time_h=NEXT_DOSE_H,
        offsets_post_dose_h=LSS_OFFSETS_H,
        seed=5,
        n_simulations=12,
    )
    assert expected == pytest.approx(0.7608, abs=5e-4), (
        f"expected calibration drifted to {expected:.4f} — if the simulation was changed "
        "deliberately, re-measure and update this pin in the same change"
    )
