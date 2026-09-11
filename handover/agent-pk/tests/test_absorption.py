"""test_absorption.py — the multi-time-point claim, tested as a claim and corrected by it.

THE FIRST VERSION OF THIS FILE ASSERTED THE WRONG THING, AND MEASURING IT IS WHAT SHOWED THAT.
It claimed a limited-sampling curve gives a NARROWER and MORE ACCURATE next-trough prediction
than four troughs. Both halves are false, and the reasons are worth keeping:

  * A trough is the point on the curve carrying the least absorption information, so four
    troughs predict the next trough perfectly well. The curve interval was WIDER (2.09 vs 1.16
    ng/mL) — correctly so, because it honestly carries absorption uncertainty the trough-only
    fit simply assumes away.
  * On magnitude of exposure error the curve barely wins at all: mean |error| 7.6% against 8.0%
    over 24 seeds.

What the curve actually buys is the removal of a systematic BIAS. The population prior pulls a
sparse fit toward itself, and for a patient far from the population mean that pull inflates
estimated exposure — measured at +19.8% for a patient at 1.62x the prior clearance, against
-1.5% for the same patient sampled on a curve. A clearance 1.62x the population mean is almost
exactly the 1.64x CYP3A5 expresser factor, so the patient this hurts most is the one the
session-1 genotype finding was about.

The published ~40% error reduction is measured against an A PRIORI prediction with no individual
data at all. Our baseline already has four troughs and thirty days of stable dosing on a
correctly-specified model. We do not reproduce that number here and do not claim it.

The identifiability guard is tested in both directions, which is the part a happy-path suite
would miss: absorption must be estimated when the data can support it AND must be left at the
prior when it cannot. A third parameter fitted to data that cannot separate it returns a
confident number for something nobody measured.

Every patient here is synthetic and generated from a seeded RNG.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from agent_pk.pk.fit import (
    FitResult,
    absorption_is_identifiable,
    count_absorption_informative_observations,
    fit_individual,
    predict_trough,
)
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

# A once-daily extended-release patient — the formulation the demo commits to.
DOSE_INTERVAL_H = 24.0
DOSE_MG = 4.0
N_DAYS = 30

TRUE_CLEARANCE_L_PER_H = 26.0
TRUE_VOLUME_L = 350.0
TRUE_KA_PER_H = 3.2
"""Deliberately well away from the published FIXED value of 2.0/h, so that recovering it
demonstrates the DATA moved the estimate rather than the prior holding it in place.

Note what estimating absorption at all means here: the source model FIXES ka because its own
data could not identify it. A fit that estimates it is an extension beyond the source, resting
on a prior width that is ours — see `priors.OMEGA_LOG_KA`."""

# The validated four-point schedule: C0-C1-C3-C6. The authors of the 2026 Frontiers in
# Immunology study recommend this combination after validation (R2 0.962, MAPE 5.46%), NOT the
# C0-C1-C4-C6 combination that scores marginally higher on the derivation set. Selecting on
# derivation R2 over validated performance is how a model gets chosen by overfitting.
LSS_OFFSETS_H = (0.0, 1.0, 3.0, 6.0)


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


def _true_params() -> PkParameters:
    return _params(TRUE_CLEARANCE_L_PER_H, TRUE_VOLUME_L, TRUE_KA_PER_H)


def _dosing_history(n_days: int = N_DAYS) -> tuple[DoseEvent, ...]:
    """Once-daily dosing for n_days, every dose taken."""
    return tuple(
        DoseEvent(time_h=index * DOSE_INTERVAL_H, amount_mg=DOSE_MG, status="taken")
        for index in range(n_days)
    )


def _simulate(
    doses: tuple[DoseEvent, ...],
    sample_times_h: tuple[float, ...],
    seed: int,
    proportional_cv: float = 0.18,
) -> tuple[Observation, ...]:
    """Generate noisy measurements from the true model at the given times."""
    rng = np.random.default_rng(seed)
    params = _true_params()
    observations = []
    for time_h in sample_times_h:
        true_conc = concentration_at(time_h, doses, params)
        noisy = true_conc * (1.0 + proportional_cv * float(rng.standard_normal()))
        observations.append(Observation(time_h, max(noisy, 0.01)))
    return tuple(observations)


def _trough_times(n: int) -> tuple[float, ...]:
    """The last n troughs — each immediately before the next dose."""
    return tuple((N_DAYS - n + index) * DOSE_INTERVAL_H - 0.05 for index in range(n))


def _curve_times() -> tuple[float, ...]:
    """One C0-C1-C3-C6 curve around the final dose."""
    last_dose_h = (N_DAYS - 1) * DOSE_INTERVAL_H
    return tuple(last_dose_h + offset for offset in LSS_OFFSETS_H)


def _er_prior():  # type: ignore[no-untyped-def]
    return prior_for(
        Covariates(formulation="advagraf_prolonged_release", cyp3a5_expresser=False)
    )


# ── The identifiability guard, in both directions ────────────────────────────


def test_troughs_alone_do_not_identify_absorption() -> None:
    """Trough-only is not a degraded three-parameter fit. It is the correct two-parameter one."""
    doses = _dosing_history()
    observations = _simulate(doses, _trough_times(4), seed=11)
    assert absorption_is_identifiable(doses, observations) is False

    fit = fit_individual(doses, observations, _er_prior())
    assert fit.estimated_ka is False
    assert len(fit.log_theta) == 2
    assert len(fit.covariance) == 2
    assert fit.parameters.ka_per_h == pytest.approx(KA_PER_H)


def test_a_limited_sampling_curve_identifies_absorption() -> None:
    doses = _dosing_history()
    observations = _simulate(doses, _curve_times(), seed=11)
    assert count_absorption_informative_observations(doses, observations) == 3
    assert absorption_is_identifiable(doses, observations) is True

    fit = fit_individual(doses, observations, _er_prior())
    assert fit.estimated_ka is True
    assert len(fit.log_theta) == 3
    assert len(fit.covariance) == 3


def test_one_post_dose_point_is_not_enough() -> None:
    """A single early concentration cannot separate a faster ka from a smaller volume."""
    doses = _dosing_history()
    last_dose_h = (N_DAYS - 1) * DOSE_INTERVAL_H
    observations = _simulate(doses, (*_trough_times(3), last_dose_h + 1.0), seed=12)
    assert count_absorption_informative_observations(doses, observations) == 1
    assert absorption_is_identifiable(doses, observations) is False
    assert fit_individual(doses, observations, _er_prior()).estimated_ka is False


def test_a_missed_dose_starts_no_absorption_phase() -> None:
    """Timing from a dose that delivered nothing measures a trough, whatever the schedule said."""
    doses = (
        DoseEvent(time_h=0.0, amount_mg=DOSE_MG, status="taken"),
        DoseEvent(time_h=24.0, amount_mg=DOSE_MG, status="missed"),
    )
    observations = (
        Observation(time_h=25.0, concentration_ng_per_ml=5.0),
        Observation(time_h=27.0, concentration_ng_per_ml=4.6),
    )
    # Both are within 8 h of the MISSED dose, but that dose delivered nothing. They are timed
    # from the 0 h dose instead, which is more than 8 h earlier.
    assert count_absorption_informative_observations(doses, observations) == 0
    assert absorption_is_identifiable(doses, observations) is False


def test_a_vomited_dose_starts_no_absorption_phase() -> None:
    doses = (
        DoseEvent(time_h=0.0, amount_mg=DOSE_MG, status="taken"),
        DoseEvent(time_h=24.0, amount_mg=DOSE_MG, status="vomited"),
    )
    observations = (Observation(time_h=25.0, concentration_ng_per_ml=5.0),)
    assert count_absorption_informative_observations(doses, observations) == 0


# ── The claim the product actually makes ─────────────────────────────────────


# REMOVED: the trough-only exposure-bias tests, and the `_exposure_bias` helper that fed them.
#
# They asserted a finding this project DERIVED from its own simulations — that trough-only
# fitting overstates exposure by ~20% for a patient at 1.6x the population clearance, and that
# a four-point curve removes that bias. Both numbers were properties of a population prior that
# had been invented rather than taken from a published model. Re-measured against the model this
# module now uses (Fernandez-Alarcon 2024), the effect is about a quarter of the claimed size and
# the curve is consistently the MORE biased of the two, not the less: 24-hour exposure is
# essentially Dose/CL, clearance is identified by the terminal phase, and troughs sample that
# phase while a C0-C1-C3-C6 curve does not.
#
# The tests are deleted rather than re-baselined against the new numbers, which is the point:
# this product's science rests on a published population model and a published limited-sampling
# equation, both cited. It does not rest on findings we generate from synthetic patients and then
# defend. What the sampling curve buys is stated where it is now claimed — the published equation
# becomes runnable, giving an independent cross-check — and that claim is structural, not measured.


def test_absorption_is_estimated_but_a_single_curve_does_not_pin_it() -> None:
    """An honest statement of what one four-point curve buys, and what it does not.

    Measured over 24 seeded patients: the fitted ka beat the prior on 12 of them, with mean log
    error 0.423 against the prior's 0.492. That is a coin flip, so this test asserts only what
    is robustly true — that absorption is ESTIMATED, that the estimate is physically valid, and
    that its uncertainty is carried into the interval rather than hidden. Asserting per-patient
    recovery would be asserting a result the measurement does not support.
    """
    doses = _dosing_history()
    fit = fit_individual(doses, _simulate(doses, _curve_times(), seed=7), _er_prior())

    assert fit.estimated_ka is True
    assert fit.parameters.ka_per_h > 0.0
    assert math.isfinite(fit.parameters.ka_per_h)
    # The absorption variance is real and carried, not a placeholder zero.
    assert fit.covariance[2][2] > 0.0


def test_absorption_uncertainty_is_propagated_not_collapsed() -> None:
    """Sampling CL and V while pinning ka at its mode would understate the interval.

    A narrower interval is exactly how a boundary crossing goes unreported, so this is a safety
    property rather than a statistical nicety. The three-parameter posterior must produce a
    wider interval than the same posterior with absorption held fixed at its own point estimate.
    """
    doses = _dosing_history()
    observations = _simulate(doses, _curve_times(), seed=5)
    fit = fit_individual(doses, observations, _er_prior())
    assert fit.estimated_ka is True

    target_h = N_DAYS * DOSE_INTERVAL_H - 0.05
    full = predict_trough(doses, fit, target_h, 5.0, 8.0, seed=2)

    # The same fit with absorption collapsed to its mode: drop the third row and column.
    collapsed = FitResult(
        parameters=fit.parameters,
        log_theta=fit.log_theta[:2],
        covariance=tuple(row[:2] for row in fit.covariance[:2]),
        n_observations=fit.n_observations,
        converged=fit.converged,
        uncertainty_source=fit.uncertainty_source,
        haematocrit_known=fit.haematocrit_known,
        haematocrit=fit.haematocrit,
        residual_cv=fit.residual_cv,
    )
    pinned = predict_trough(doses, collapsed, target_h, 5.0, 8.0, seed=2)

    full_width = full.upper_ng_per_ml - full.lower_ng_per_ml
    pinned_width = pinned.upper_ng_per_ml - pinned.lower_ng_per_ml
    assert full_width > pinned_width, (
        f"propagating absorption uncertainty gave {full_width:.3f}, no wider than the "
        f"{pinned_width:.3f} from pinning it — the uncertainty is being dropped"
    )


# ── Three-dimensional covariance validation ──────────────────────────────────


def test_a_positive_determinant_does_not_rescue_an_indefinite_3x3() -> None:
    """The reason the check is Cholesky and not a determinant.

    At 2x2, a positive diagonal plus a positive determinant IS Sylvester's criterion. At 3x3 it
    is not: a matrix with TWO negative eigenvalues has a positive determinant and would sail
    through a determinant test straight into the sampler. This witness has exactly that shape.
    """
    # Unit diagonal with off-diagonals of 2 gives eigenvalues {1+2r, 1-r, 1-r} = {5, -1, -1}:
    # determinant +5, two negative eigenvalues, and a positive diagonal so it survives every
    # cheaper check and reaches the Cholesky test.
    covariance = (
        (1.0, 2.0, 2.0),
        (2.0, 1.0, 2.0),
        (2.0, 2.0, 1.0),
    )
    matrix = np.array(covariance, dtype=float)
    eigenvalues = np.linalg.eigvalsh(matrix)
    assert float(np.linalg.det(matrix)) > 0.0, (
        "witness must have a positive determinant"
    )
    assert int(np.sum(eigenvalues < 0.0)) == 2, (
        "witness must have two negative eigenvalues"
    )

    with pytest.raises(PkInputError, match="positive-definite"):
        FitResult(
            parameters=_true_params(),
            log_theta=(math.log(26.0), math.log(560.0), math.log(2.2)),
            covariance=covariance,
            n_observations=4,
            converged=True,
            uncertainty_source="prior",
            haematocrit_known=True,
            haematocrit=0.45,
            residual_cv=0.282,
        )


def test_covariance_size_must_match_the_parameter_vector() -> None:
    with pytest.raises(PkInputError, match="to match log_theta"):
        FitResult(
            parameters=_true_params(),
            log_theta=(math.log(26.0), math.log(560.0), math.log(2.2)),
            covariance=((0.1, 0.0), (0.0, 0.1)),
            n_observations=4,
            converged=True,
            uncertainty_source="prior",
            haematocrit_known=True,
            haematocrit=0.45,
            residual_cv=0.282,
        )


def test_an_unsupported_parameter_count_is_refused() -> None:
    with pytest.raises(PkInputError, match="2 parameters"):
        FitResult(
            parameters=_true_params(),
            log_theta=(math.log(26.0),),
            covariance=((0.1,),),
            n_observations=1,
            converged=True,
            uncertainty_source="prior",
            haematocrit_known=True,
            haematocrit=0.45,
            residual_cv=0.282,
        )


# ── Formulation is a first-class field ───────────────────────────────────────


def test_the_immediate_release_formulation_is_refused_rather_than_approximated() -> (
    None
):
    """There is no published immediate-release model here, so there is no IR prior.

    An earlier revision offered `twice_daily_ir` and supplied it with an absorption constant
    nobody had published for it. Refusing is the honest answer: a caller who needs IR needs a
    different source model, not this one's parameters wearing the wrong label.
    """
    with pytest.raises(PkInputError, match="no published immediate-release model"):
        Covariates(formulation="twice_daily_ir")  # type: ignore[arg-type]


def test_the_absorption_prior_is_the_published_fixed_value() -> None:
    er = prior_for(Covariates(formulation="advagraf_prolonged_release"))
    assert er.ka_per_h == pytest.approx(KA_PER_H)
    assert er.lag_h == pytest.approx(LAG_H)
    assert er.formulation == "advagraf_prolonged_release"
    assert er.log_ka_mean == pytest.approx(math.log(er.ka_per_h))


def test_an_unknown_formulation_is_refused() -> None:
    """A typo must not silently inherit the immediate-release prior."""
    with pytest.raises(PkInputError, match="formulation must be one of"):
        Covariates(formulation="once_daily")  # type: ignore[arg-type]


def test_the_default_formulation_is_the_only_published_one() -> None:
    """Asserted so a future default change is a deliberate act rather than a drift."""
    assert Covariates().formulation == "advagraf_prolonged_release"
    assert prior_for(Covariates()).ka_per_h == pytest.approx(KA_PER_H)
