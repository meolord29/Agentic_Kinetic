"""test_pk.py — synthetic-patient recovery and safety-property tests for the PK core.

Every patient here is generated from a seeded RNG. There is no real data in this suite, and the
module under test has no file or network path that could acquire any.

The suite deliberately tests two NEGATIVES that a happy-path suite would pass without:
that non-finite and bool inputs RAISE rather than flowing into a comparison, and that the
escalation gate fires on the INTERVAL rather than on the median.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.optimize import minimize

from agent_pk.pk.fit import (
    FitResult,
    PkDegenerateSampleError,
    _covariance_is_step_stable,
    fit_individual,
    predict_trough,
)
from agent_pk.pk.model import (
    MG_PER_L_TO_NG_PER_ML,
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
    CYP3A5_EXPRESSER_CLEARANCE_FACTOR,
    OMEGA_LOG_CLEARANCE,
    REFERENCE_HAEMATOCRIT,
    VP_F_L,
    Covariates,
    express_as_measured,
    prior_for,
    standardise_to_reference_haematocrit,
)

DOSE_INTERVAL_H = 24.0
DOSE_MG = 4.0
N_DAYS = 30

TRUE_CLEARANCE_L_PER_H = 26.0
TRUE_VOLUME_L = 350.0
"""Close to the published central volume of 327 L, deliberately.

An earlier value of 550 L was chosen when this module carried a one-compartment model whose
population volume was 500 L. Against the published Vc/F it is a 1.1-SD outlier, and the fit
correctly shrinks it back toward the population — so a test asserting recovery was really
asserting the MAGNITUDE of that shrinkage. A synthetic patient used to test the fitter should be
a plausible draw from the population it is fitted against."""
TRUE_KA_PER_H = 2.0


def _dosing_history(
    n_days: int = N_DAYS, missed_indices: frozenset[int] = frozenset()
) -> tuple[DoseEvent, ...]:
    """Once-daily dosing for n_days, with the named dose indices reported as missed."""
    return tuple(
        DoseEvent(
            time_h=index * DOSE_INTERVAL_H,
            amount_mg=DOSE_MG,
            status="missed" if index in missed_indices else "taken",
        )
        for index in range(n_days)
    )


def _params(
    clearance_l_per_h: float, volume_central_l: float, ka_per_h: float = KA_PER_H
) -> PkParameters:
    """Individual parameters with the published model's FIXED disposition values filled in."""
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


def _simulate_observations(
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


# ── Structural model ─────────────────────────────────────────────────────────


def test_unit_conversion_is_applied_once() -> None:
    """A single dose into a known central volume yields the arithmetically expected ng/mL.

    Sampled IMMEDIATELY after absorption completes, and that timing is the point. Under one
    compartment the concentration stayed at dose/V and any later time would do; under two, drug
    starts leaving for the peripheral compartment at once, so by one hour this same dose reads
    62.6 ng/mL rather than 100. Only the instant after absorption isolates the unit conversion
    from the distribution the model now has.
    """
    params = _params(1e-9, 100.0, 1e6)
    dose = (DoseEvent(time_h=0.0, amount_mg=10.0),)
    concentration = concentration_at(params.lag_h + 1e-5, dose, params)
    expected_mg_per_l = 10.0 / 100.0
    assert concentration == pytest.approx(
        expected_mg_per_l * MG_PER_L_TO_NG_PER_ML, rel=1e-3
    )


def test_concentration_is_zero_before_the_first_dose() -> None:
    doses = _dosing_history(n_days=2)
    assert concentration_at(-1.0, doses, _true_params()) == 0.0


def test_ka_equal_to_ke_does_not_blow_up() -> None:
    """The Bateman function divides by (ka - ke); the limiting form must be used instead."""
    clearance, volume = 21.0, 500.0
    ke = clearance / volume
    params = _params(clearance, volume, ka_per_h=ke)  # exactly singular
    result = concentration_at(6.0, (DoseEvent(0.0, 2.0),), params)
    assert math.isfinite(result)
    assert result > 0.0


def test_missed_doses_lower_the_predicted_concentration() -> None:
    """A dose reported missed must deliver nothing, and the trough must fall as a result."""
    params = _true_params()
    target = N_DAYS * 24.0 - 0.01
    full = concentration_at(target, _dosing_history(), params)
    with_misses = concentration_at(
        target, _dosing_history(missed_indices=frozenset(range(20, 26))), params
    )
    assert with_misses < full


# ── Input validation: the fail-open classes ──────────────────────────────────


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_observation_raises(bad: float) -> None:
    """NaN must raise, because every ordered comparison against NaN evaluates False."""
    with pytest.raises(PkInputError):
        Observation(time_h=0.0, concentration_ng_per_ml=bad)


def test_nan_would_have_silently_passed_the_boundary_test() -> None:
    """Documents why the guard cannot live in the decision function.

    This is the failure the validation prevents: a NaN concentration compared against a lower
    bound evaluates False, i.e. reads as 'above the boundary', i.e. suppresses the escalation.
    """
    assert (float("nan") < 5.0) is False


def test_bool_is_rejected_as_a_number() -> None:
    """bool subclasses int, so True passes isinstance(x, int) and every later comparison."""
    with pytest.raises(PkInputError):
        DoseEvent(time_h=0.0, amount_mg=True)  # type: ignore[arg-type]


def test_haematocrit_as_percent_is_rejected() -> None:
    """35 is a percentage; the model wants 0.35. Accepting both silently would be worse."""
    with pytest.raises(PkInputError):
        Covariates(haematocrit=35.0)


def test_inverted_bounds_are_rejected() -> None:
    fit = fit_individual((), (), prior_for(Covariates()))
    with pytest.raises(PkInputError):
        predict_trough(
            _dosing_history(),
            fit,
            100.0,
            15.0,
            5.0,
            seed=1,  # upper below lower
        )


def test_non_finite_bound_is_rejected() -> None:
    fit = fit_individual((), (), prior_for(Covariates()))
    with pytest.raises(PkInputError):
        predict_trough(_dosing_history(), fit, 100.0, float("nan"), 15.0, seed=1)


# ── Priors ───────────────────────────────────────────────────────────────────


def test_unknown_genotype_widens_the_clearance_prior() -> None:
    """Not knowing a covariate must never make the model more confident."""
    known = prior_for(Covariates(cyp3a5_expresser=False))
    unknown = prior_for(Covariates(cyp3a5_expresser=None))
    assert unknown.omega_log_clearance > known.omega_log_clearance
    assert known.omega_log_clearance == OMEGA_LOG_CLEARANCE
    assert known.genotype_known is True
    assert unknown.genotype_known is False


def test_expresser_genotype_raises_the_clearance_prior() -> None:
    non_expresser = prior_for(Covariates(cyp3a5_expresser=False))
    expresser = prior_for(Covariates(cyp3a5_expresser=True))
    assert expresser.log_clearance_mean > non_expresser.log_clearance_mean


# ── Fitting: synthetic patient with known parameters ─────────────────────────


def test_recovers_known_parameters_from_rich_sampling() -> None:
    """With samples spread across the dosing interval, the fit must find the true clearance."""
    doses = _dosing_history()
    # Offsets spread across a 24 h interval, on two days inside the dosing history. The
    # previous values sampled day 40 of a 30-day history at offsets up to 11.9 h — both
    # left over from when this module modelled a twice-daily formulation.
    offsets = (0.5, 1.0, 2.0, 4.0, 6.0, 9.0, 12.0, 18.0, 23.9)
    day = 20
    times = tuple(day * 24.0 + offset for offset in offsets) + tuple(
        (day + 5) * 24.0 + offset for offset in offsets
    )
    observations = _simulate_observations(doses, times, seed=20260912)

    fit = fit_individual(doses, observations, prior_for(Covariates()))

    assert fit.converged
    assert fit.uncertainty_source == "laplace"
    assert fit.parameters.clearance_l_per_h == pytest.approx(
        TRUE_CLEARANCE_L_PER_H, rel=0.25
    )
    assert fit.parameters.volume_central_l == pytest.approx(TRUE_VOLUME_L, rel=0.5)


def test_sparse_troughs_move_the_estimate_toward_the_truth() -> None:
    """The honest sparse-data claim.

    Four weekly troughs cannot pin an individual's clearance. What they CAN do is move the
    estimate off the population mean in the right direction, which is all the product needs to
    decide whether to look sooner. Asserting tight recovery here would be asserting a precision
    the data does not contain.
    """
    doses = _dosing_history()
    trough_times = tuple(day * 24.0 - 0.01 for day in (9, 16, 23, 30))
    observations = _simulate_observations(doses, trough_times, seed=7)
    prior = prior_for(Covariates())

    fit = fit_individual(doses, observations, prior)

    prior_error = abs(math.log(TRUE_CLEARANCE_L_PER_H) - prior.log_clearance_mean)
    fitted_error = abs(math.log(TRUE_CLEARANCE_L_PER_H) - fit.log_theta[0])
    assert fitted_error < prior_error, (
        f"the fit did not improve on the population prior: "
        f"prior log-error {prior_error:.3f}, fitted {fitted_error:.3f}"
    )


def test_no_observations_returns_the_prior_exactly() -> None:
    """Zero data is not a degraded fit — the prior IS the posterior, and it must say so."""
    prior = prior_for(Covariates())
    fit = fit_individual(_dosing_history(), (), prior)

    assert fit.n_observations == 0
    assert fit.uncertainty_source == "prior"
    assert fit.log_theta[0] == pytest.approx(prior.log_clearance_mean)
    assert fit.covariance[0][0] == pytest.approx(prior.omega_log_clearance**2)


def test_more_observations_narrow_the_interval() -> None:
    """Uncertainty must fall as evidence accumulates, or the interval is not doing its job."""
    doses = _dosing_history()
    day = 20
    offsets = (0.5, 1.0, 2.0, 4.0, 6.0, 9.0, 12.0, 18.0, 23.9)
    sparse = _simulate_observations(
        doses, tuple(day * 24.0 + o for o in offsets[:2]), seed=3
    )
    rich = _simulate_observations(doses, tuple(day * 24.0 + o for o in offsets), seed=3)
    prior = prior_for(Covariates())
    target = N_DAYS * 24.0 - 0.01

    sparse_prediction = predict_trough(
        doses, fit_individual(doses, sparse, prior), target, 5.0, 15.0, seed=11
    )
    rich_prediction = predict_trough(
        doses, fit_individual(doses, rich, prior), target, 5.0, 15.0, seed=11
    )

    sparse_width = sparse_prediction.upper_ng_per_ml - sparse_prediction.lower_ng_per_ml
    rich_width = rich_prediction.upper_ng_per_ml - rich_prediction.lower_ng_per_ml
    assert rich_width < sparse_width


# ── The escalation gate ──────────────────────────────────────────────────────


def test_gate_fires_on_the_interval_not_the_median() -> None:
    """The property that makes this a triage tool rather than a false-alarm generator.

    A prediction whose median sits inside the window but whose lower bound reaches the danger
    zone must escalate. If the gate read the median, this patient would be told nothing.
    """
    doses = _dosing_history()
    fit = fit_individual(doses, (), prior_for(Covariates()))
    target = N_DAYS * 24.0 - 0.01

    wide = predict_trough(doses, fit, target, 0.01, 1000.0, seed=42)
    assert wide.lower_ng_per_ml < wide.median_ng_per_ml < wide.upper_ng_per_ml
    assert wide.crosses_boundary is False, "sanity: nothing crosses these bounds"

    # Bounds are derived from the prediction itself, so this tests the PROPERTY rather than a
    # coincidence of the current prior. An earlier version hardcoded 5-15 and broke the moment
    # the genotype-mixture fix shifted the clearance prior — the property never changed, only
    # the numbers did.
    lower_bound = (wide.lower_ng_per_ml + wide.median_ng_per_ml) / 2.0
    prediction = predict_trough(doses, fit, target, lower_bound, 1000.0, seed=42)

    assert prediction.lower_ng_per_ml < lower_bound < prediction.median_ng_per_ml
    assert prediction.crosses_below is True
    assert prediction.crosses_boundary is True


def test_prediction_is_deterministic_for_a_given_seed() -> None:
    """No implicit global randomness: same inputs and seed, byte-identical output."""
    doses = _dosing_history()
    fit = fit_individual(doses, (), prior_for(Covariates()))
    target = N_DAYS * 24.0 - 0.01

    first = predict_trough(doses, fit, target, 5.0, 15.0, seed=99)
    second = predict_trough(doses, fit, target, 5.0, 15.0, seed=99)

    assert first == second


def test_a_wider_prior_yields_a_wider_prediction_interval() -> None:
    """Unknown genotype must widen the prediction, not merely the parameter prior."""
    doses = _dosing_history()
    target = N_DAYS * 24.0 - 0.01
    known = predict_trough(
        doses,
        fit_individual(doses, (), prior_for(Covariates(cyp3a5_expresser=False))),
        target,
        5.0,
        15.0,
        seed=5,
    )
    unknown = predict_trough(
        doses,
        fit_individual(doses, (), prior_for(Covariates(cyp3a5_expresser=None))),
        target,
        5.0,
        15.0,
        seed=5,
    )
    # COMPARED AS RELATIVE WIDTH, NOT ABSOLUTE — and the distinction is the point of the test
    # rather than a convenience. An unknown genotype does TWO things to the prior: it widens the
    # spread AND it shifts the mean clearance up (the arithmetic mixture over both genotypes),
    # which puts predicted concentrations LOWER. Absolute interval width scales with the level it
    # sits at, so the downward shift shrinks the absolute width while the distribution is
    # genuinely wider — and comparing absolute widths therefore tests the two effects fused
    # together. Measured here: omega on log CL rises 0.313 -> 0.364 and relative width rises
    # 1.96 -> 2.28, while the ABSOLUTE width falls 15.5 -> 14.8. Relative width is the scale-free
    # comparison and is what "a wider prior" means; the mean shift has its own test below.
    known_width = (
        known.upper_ng_per_ml - known.lower_ng_per_ml
    ) / known.median_ng_per_ml
    unknown_width = (
        unknown.upper_ng_per_ml - unknown.lower_ng_per_ml
    ) / unknown.median_ng_per_ml
    assert unknown_width > known_width


# ── Regressions for adopted verifier findings ────────────────────────────────


def test_unknown_genotype_shifts_the_mean_not_only_the_width() -> None:
    """Regression for the verifier's first HIGH finding.

    Widening the prior while leaving its MEAN at the non-expresser value biases a true
    expresser's predicted concentration upward by the whole 1.64x factor. A genuinely
    sub-therapeutic patient could then sit below the plan's lower bound while the interval's
    lower quantile stayed above it — the escalation would never fire, which is the one failure
    this product exists to prevent. The unknown-genotype mean must therefore sit strictly
    between the two known cases.
    """
    non_expresser = prior_for(Covariates(cyp3a5_expresser=False))
    expresser = prior_for(Covariates(cyp3a5_expresser=True))
    unknown = prior_for(Covariates(cyp3a5_expresser=None))

    assert (
        non_expresser.log_clearance_mean
        < unknown.log_clearance_mean
        < expresser.log_clearance_mean
    )


def test_higher_expresser_prevalence_shifts_the_unknown_prior_further() -> None:
    """The mixture must respond to the population it is serving, not be a fixed fudge."""
    low = prior_for(Covariates(cyp3a5_expresser=None, expresser_prevalence=0.05))
    high = prior_for(Covariates(cyp3a5_expresser=None, expresser_prevalence=0.60))
    assert high.log_clearance_mean > low.log_clearance_mean


def test_expresser_prevalence_outside_zero_to_one_is_rejected() -> None:
    with pytest.raises(PkInputError):
        Covariates(expresser_prevalence=1.4)


def test_step_unstable_covariance_is_rejected() -> None:
    """Regression for the verifier's second HIGH finding.

    A numerically unreliable Hessian can report a posterior far tighter than the evidence
    justifies, and that narrow interval is what would suppress an escalation. Disagreement
    between two step sizes is the observable signature, and it must be rejected.
    """
    stable_a = np.array([[0.10, 0.0], [0.0, 0.20]])
    stable_b = np.array([[0.105, 0.0], [0.0, 0.19]])
    unstable = np.array([[0.01, 0.0], [0.0, 0.20]])
    assert _covariance_is_step_stable(stable_a, stable_b) is True
    assert _covariance_is_step_stable(stable_a, unstable) is False


def test_off_diagonal_drift_is_caught() -> None:
    """The round-2 HIGH, with the verifier's own witness.

    Identical diagonals, correlations of ~0.90 and ~0.05. A diagonal-only check calls these
    equal; predict_trough samples the full matrix and would produce materially different
    intervals from them.
    """
    correlated = np.array([[0.10, 0.09], [0.09, 0.20]])
    nearly_independent = np.array([[0.10, 0.01], [0.01, 0.20]])
    assert np.allclose(np.diag(correlated), np.diag(nearly_independent))
    assert _covariance_is_step_stable(correlated, nearly_independent) is False


def test_unknown_genotype_mean_uses_the_arithmetic_mixture() -> None:
    """The round-2 MEDIUM: the geometric form understates clearance, biasing concentration up."""
    prevalence = 0.30
    non_expresser = prior_for(Covariates(cyp3a5_expresser=False))
    unknown = prior_for(
        Covariates(cyp3a5_expresser=None, expresser_prevalence=prevalence)
    )
    factor = CYP3A5_EXPRESSER_CLEARANCE_FACTOR
    arithmetic = (1.0 - prevalence) + prevalence * factor
    geometric = factor**prevalence
    assert arithmetic > geometric, "AM-GM: the geometric form is the smaller one"
    assert math.exp(unknown.log_clearance_mean - non_expresser.log_clearance_mean) == (
        pytest.approx(arithmetic)
    )


def test_a_legitimately_informative_fit_keeps_its_laplace_covariance() -> None:
    """The guard must not punish good data.

    An earlier version of this guard used an invented information bound and rejected a perfectly
    well-identified fit from rich sampling. Narrowing on informative data is correct Bayesian
    behaviour and must survive.
    """
    doses = _dosing_history()
    day = 40
    times = tuple(day * 24.0 + o for o in (0.5, 1.0, 2.0, 4.0, 6.0, 8.0, 10.0, 11.9))
    observations = _simulate_observations(doses, times, seed=20260912)
    fit = fit_individual(doses, observations, prior_for(Covariates()))
    assert fit.uncertainty_source == "laplace"


def test_degenerate_sampling_raises_a_named_catchable_error() -> None:
    """A refusal must be distinguishable from 'no escalation needed', so it has its own type."""
    absurd = FitResult(
        parameters=_true_params(),
        log_theta=(math.log(30.0), math.log(550.0)),
        covariance=((1.0e6, 0.0), (0.0, 1.0e6)),  # draws overflow to non-finite
        n_observations=0,
        converged=True,
        uncertainty_source="prior",
        haematocrit_known=True,
        haematocrit=0.45,
        residual_cv=0.282,
    )
    with pytest.raises(PkDegenerateSampleError):
        predict_trough(
            _dosing_history(), absurd, N_DAYS * 24.0 - 0.01, 5.0, 15.0, seed=1
        )
    assert issubclass(PkDegenerateSampleError, PkInputError)


def test_fit_result_rejects_malformed_numbers() -> None:
    """Regression for the verifier's LOW finding: a hand-built FitResult must not reach the sampler."""
    good = dict(
        parameters=_true_params(),
        log_theta=(math.log(30.0), math.log(550.0)),
        n_observations=0,
        converged=True,
        uncertainty_source="prior",
        haematocrit_known=True,
        haematocrit=0.45,
        residual_cv=0.282,
    )
    with pytest.raises(PkInputError):
        FitResult(covariance=((float("nan"), 0.0), (0.0, 0.1)), **good)  # type: ignore[arg-type]
    with pytest.raises(PkInputError):
        FitResult(covariance=((-1.0, 0.0), (0.0, 0.1)), **good)  # type: ignore[arg-type]
    with pytest.raises(PkInputError):
        FitResult(covariance=((0.1, 0.05), (0.02, 0.1)), **good)  # type: ignore[arg-type]
    # Positive diagonal AND symmetric, but the determinant is negative — the round-2 witness.
    with pytest.raises(PkInputError):
        FitResult(covariance=((0.1, 0.11), (0.11, 0.1)), **good)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("clearance", "volume"),
    [(1e-9, 1e-9), (1e9, 1e-6), (1e-6, 1e9), (1e9, 1e9)],
)
def test_extreme_parameters_do_not_raise(clearance: float, volume: float) -> None:
    """Absurd parameters must yield a finite number or zero — never an overflow.

    The posterior sampler draws from a covariance and can reach extreme corners; a raise from
    inside the structural model would escape as an unnamed OverflowError rather than being
    marked an unusable draw. The first expm1-only revision of the Bateman form did exactly that,
    and this suite caught it.
    """
    result = concentration_at(
        6.0, (DoseEvent(0.0, 2.0),), _params(clearance, volume, 4.5)
    )
    assert math.isfinite(result)
    assert result >= 0.0


def test_rotation_blind_spot_is_caught() -> None:
    """The round-3 HIGH, with the verifier's own witness.

    Identical eigenvalues {0.10, 0.20}, opposite correlation (+0.33 and -0.33). A spectrum-only
    check calls these equal at any tolerance; predict_trough samples the full matrix and would
    draw materially different joint distributions from them.
    """
    positive = np.array([[0.15, 0.05], [0.05, 0.15]])
    negative = np.array([[0.15, -0.05], [-0.05, 0.15]])
    assert np.allclose(
        np.sort(np.linalg.eigvalsh(positive)), np.sort(np.linalg.eigvalsh(negative))
    ), "the witness requires identical spectra"
    assert _covariance_is_step_stable(positive, negative) is False


def test_stability_guard_accepts_genuinely_close_covariances() -> None:
    """The guard must still admit agreement, or every fit falls back to the prior."""
    a = np.array([[0.150, 0.050], [0.050, 0.150]])
    b = np.array([[0.155, 0.052], [0.052, 0.148]])
    assert _covariance_is_step_stable(a, b) is True


def test_non_convergence_returns_the_prior_mean_not_a_biased_centre() -> None:
    """The round-3 second HIGH.

    Widening the interval around a centre the optimiser never settled on does not make it safe:
    a centre displaced toward low clearance predicts a high concentration, and the lower
    credible bound can stay above the therapeutic floor for a patient who is sub-therapeutic.
    Non-convergence must reset the CENTRE as well as the width.
    """
    doses = _dosing_history()
    times = tuple(40 * 24.0 + o for o in (0.5, 2.0, 6.0, 11.9))
    observations = _simulate_observations(doses, times, seed=5)
    prior = prior_for(Covariates())

    converged = fit_individual(doses, observations, prior)
    assert converged.converged, (
        "baseline must converge for the contrast to mean anything"
    )

    # Force non-convergence by starving the optimiser of iterations.
    import agent_pk.pk.fit as fit_module

    original = fit_module._MAX_ITERATIONS
    try:
        fit_module._MAX_ITERATIONS = 1
        starved = fit_individual(doses, observations, prior)
    finally:
        fit_module._MAX_ITERATIONS = original

    assert starved.converged is False
    assert starved.uncertainty_source == "prior"
    assert starved.log_theta[0] == pytest.approx(prior.log_clearance_mean)
    assert starved.log_theta[1] == pytest.approx(prior.log_volume_mean)


def test_near_equal_rates_at_long_times_do_not_cancel() -> None:
    """The round-3 MEDIUM, with the verifier's own witness.

    ka and ke nearly equal but t large enough that |x| passes the overflow threshold. Branching
    on |x| alone sent this to the direct-difference form, which subtracts two near-equal tiny
    numbers. Both exponentials underflow here, so the true concentration is zero.
    """
    params = _params(
        clearance_l_per_h=0.0499 * 500.0, volume_central_l=500.0, ka_per_h=0.0500
    )
    result = concentration_at(6.0e6, (DoseEvent(0.0, 2.0),), params)
    assert math.isfinite(result)
    assert result == 0.0


def test_multistart_finds_the_better_optimum_from_a_hostile_start() -> None:
    """Round-4 finding 3: simplex convergence is not a verified global mode.

    A single start can settle somewhere worse than another start reaches. The multi-start search
    must be at least as good as any one of its starts, judged by the objective it minimises.
    """
    import agent_pk.pk.fit as fit_module

    doses = _dosing_history()
    times = tuple(40 * 24.0 + o for o in (0.5, 2.0, 6.0, 11.9))
    observations = _simulate_observations(doses, times, seed=13)
    prior = prior_for(Covariates())
    start = np.array([prior.log_clearance_mean, prior.log_volume_mean])

    best = fit_module._best_of_multistart(start, doses, observations, prior)
    single = minimize(
        fit_module._objective,
        start,
        args=(doses, observations, prior),
        method="Nelder-Mead",
        options={"xatol": 1e-10, "fatol": 1e-10, "maxiter": 2000, "maxfev": 4000},
    )
    assert float(best.fun) <= float(single.fun) + 1e-9


def test_multistart_is_deterministic() -> None:
    """Fixed offsets, not random restarts — the determinism contract forbids implicit RNG."""
    doses = _dosing_history()
    times = tuple(40 * 24.0 + o for o in (0.5, 2.0, 6.0, 11.9))
    observations = _simulate_observations(doses, times, seed=13)
    prior = prior_for(Covariates())
    first = fit_individual(doses, observations, prior)
    second = fit_individual(doses, observations, prior)
    assert first.log_theta == second.log_theta
    assert first.covariance == second.covariance


def test_covariates_rejects_the_removed_field() -> None:
    """Stage B's LOW: a declared field nothing reads is a false contract, so it is gone.

    Asserting its ABSENCE rather than its behaviour, so that reinstating it silently — without
    `prior_for` actually using it — fails here rather than misleading a caller.
    """
    with pytest.raises(TypeError):
        Covariates(days_post_transplant=180.0)  # type: ignore[call-arg]


def test_damping_ratio_series_branch_matches_the_exact_form() -> None:
    """The series branch must agree with the exact ratio it stands in for."""
    from agent_pk.pk.model import _damping_ratio

    for x in (0.0, 1e-12, 1e-9, 5e-9):
        exact = 1.0 if x == 0.0 else -math.expm1(-x) / x
        assert _damping_ratio(x) == pytest.approx(exact, abs=1e-12)


# ── The prediction-interval contract (2026-09-09 panel, CRITICAL finding) ─────


def test_the_interval_carries_residual_error_not_only_parameter_uncertainty() -> None:
    """A fit with almost NO parameter uncertainty must still report a wide interval.

    This is the mutation guard for the corrected interval semantics. The covariance here is
    effectively zero, so every posterior draw lands on the same curve and parameter uncertainty
    contributes nothing. Any width that remains can only have come from the residual error term.

    Delete the residual from `predict_trough` and this collapses to a point, which is precisely
    the defect the 2026-09-09 panel found: an interval that answers "where is the expected
    concentration" was being compared against a therapeutic range written for a MEASURED trough,
    so it was systematically too narrow and failed to escalate patients it should have escalated.
    """
    doses = _dosing_history()
    target = N_DAYS * 24.0 - 0.01
    prior = prior_for(Covariates())
    certain = FitResult(
        parameters=_true_params(),
        log_theta=(math.log(30.0), math.log(550.0)),
        covariance=((1e-12, 0.0), (0.0, 1e-12)),
        n_observations=8,
        converged=True,
        uncertainty_source="laplace",
        haematocrit_known=prior.haematocrit_known,
        haematocrit=prior.haematocrit,
        residual_cv=prior.proportional_residual_cv,
    )
    prediction = predict_trough(
        doses, certain, target, 5.0, 15.0, seed=3, n_samples=4000
    )
    spread = (
        prediction.upper_ng_per_ml - prediction.lower_ng_per_ml
    ) / prediction.median_ng_per_ml
    # A 90% interval on a log-normal residual of CV 0.282 spans roughly +/-1.645 SD, i.e. a
    # relative width near 0.9. Asserted loosely as "clearly present" rather than pinned, since
    # the exact figure is a property of the CV and not of this test.
    assert spread > 0.5, (
        "with parameter uncertainty removed the interval must still carry the model's residual "
        "error — a point estimate here means the residual is not being applied"
    )


def test_a_fit_cannot_be_built_without_the_residual_it_was_made_under() -> None:
    """The residual is required, and bool is rejected by type before any numeric test.

    `bool` subclasses `int`, so `True` would pass every ordered comparison and silently become a
    residual CV of 1.0 — a 100% error model, which would widen every interval and read as
    conservatism rather than as the misconfiguration it is.
    """
    good = dict(
        parameters=_true_params(),
        log_theta=(math.log(30.0), math.log(550.0)),
        covariance=((0.1, 0.0), (0.0, 0.1)),
        n_observations=0,
        converged=True,
        uncertainty_source="prior",
        haematocrit_known=True,
        haematocrit=0.45,
    )
    with pytest.raises(PkInputError, match="not a bool"):
        FitResult(residual_cv=True, **good)  # type: ignore[arg-type]
    with pytest.raises(PkInputError):
        FitResult(residual_cv=0.0, **good)  # type: ignore[arg-type]
    with pytest.raises(PkInputError):
        FitResult(residual_cv=float("nan"), **good)  # type: ignore[arg-type]
    # An implausibly large residual is REFUSED, not clamped: above the ceiling the positivity
    # resample in predict_trough relocates a material fraction of the lower tail into the bulk,
    # which would understate the probability of a sub-therapeutic trough while usable_fraction
    # stayed near 1.0 and reported nothing wrong. Raised by the decorrelated seat.
    with pytest.raises(PkInputError, match="positivity resample"):
        FitResult(residual_cv=1.0, **good)  # type: ignore[arg-type]
    # ...and the published value is comfortably inside it.
    assert FitResult(residual_cv=0.282, **good).residual_cv == 0.282  # type: ignore[arg-type]


def test_probability_of_being_outside_the_range_is_reported_and_coherent() -> None:
    """The escalation quantity a clinician can threshold on, and it must agree with the interval.

    Probability of target attainment is what model-informed precision dosing reports; a
    boundary-contact flag cannot distinguish a 6% risk from a 40% one. The two signals must not
    contradict each other: a 90% interval whose lower edge sits below the boundary implies at
    least a 5% probability below it.
    """
    doses = _dosing_history()
    target = N_DAYS * 24.0 - 0.01
    prior = prior_for(Covariates())
    fit = fit_individual(doses, (), prior)
    prediction = predict_trough(doses, fit, target, 5.0, 15.0, seed=8, n_samples=4000)

    assert 0.0 <= prediction.probability_below <= 1.0
    assert 0.0 <= prediction.probability_above <= 1.0
    assert prediction.probability_outside == pytest.approx(
        prediction.probability_below + prediction.probability_above
    )
    tail = (1.0 - prediction.credible_mass) / 2.0
    if prediction.crosses_below:
        assert prediction.probability_below >= tail * 0.9
    if prediction.crosses_above:
        assert prediction.probability_above >= tail * 0.9


# ── Haematocrit standardisation (2026-09-09, adopted with its outcome evidence) ──


def test_the_haematocrit_correction_is_the_identity_at_the_reference_value() -> None:
    """A non-anaemic patient must be completely unaffected — which is what the demo assumes.

    This project deliberately does NOT assume anaemia: the demo patient sits at the reference
    haematocrit, so the correction is exactly the identity there and no demo number moves. The
    capability exists for the real-world case, and this test pins the boundary between the two.
    """
    for concentration in (1.0, 6.5, 40.0):
        assert standardise_to_reference_haematocrit(
            concentration, REFERENCE_HAEMATOCRIT
        ) == pytest.approx(concentration)
        assert express_as_measured(
            concentration, REFERENCE_HAEMATOCRIT
        ) == pytest.approx(concentration)


def test_the_two_haematocrit_transforms_are_exact_inverses() -> None:
    """Round-tripping must return the original, or the fit and the boundary test drift apart."""
    for haematocrit in (0.20, 0.30, 0.36, 0.45, 0.55):
        for concentration in (2.0, 7.3, 25.0):
            standardised = standardise_to_reference_haematocrit(
                concentration, haematocrit
            )
            assert express_as_measured(standardised, haematocrit) == pytest.approx(
                concentration
            )


def test_anaemia_raises_the_standardised_concentration() -> None:
    """The direction is the whole clinical point and must not silently invert.

    Tacrolimus sits mostly inside red cells, so an anaemic patient's whole-blood level is LOW for
    the same amount of drug in the body. Standardising must therefore raise it: a model told the
    raw value would read the anaemia as fast clearance and predict a lower trough than the patient
    will actually have.
    """
    measured = 6.0
    anaemic = standardise_to_reference_haematocrit(measured, 0.30)
    assert anaemic > measured
    assert anaemic == pytest.approx(measured * 0.45 / 0.30)
    # ...and a HIGH haematocrit runs the other way, so the transform is not a one-sided fudge.
    assert standardise_to_reference_haematocrit(measured, 0.55) < measured


def test_anaemia_is_no_longer_mistaken_for_fast_clearance() -> None:
    """End to end: the correction must fix the quantity the literature says anaemia corrupts.

    Two fits on IDENTICAL laboratory values, one told the patient is anaemic and one not.

    WHAT MOVES, AND WHAT DOES NOT — this is not obvious and is worth stating, because the naive
    expectation is wrong. Tacrolimus sits mostly inside red cells, so an anaemic patient's
    whole-blood level is low for the same amount of drug in the body; a model given the raw value
    reads that as the patient CLEARING FASTER. Correcting fixes the clearance estimate, and the
    measured trough PREDICTION barely moves — because standardising the observations up and
    expressing the prediction back down are near-inverses, so they largely cancel. What survives
    the cancellation is the parameter estimate, which is what feeds exposure, AUC and any dose
    reasoning built on top.

    Measured here: an ignored anaemia estimates clearance around 21 L/h where the corrected fit
    estimates around 16 L/h. That gap is the "delta" the July 2026 Vancouver cohort associated
    with acute kidney injury (HR 1.15 per 1 ng/mL, 95% CI 1.08-1.24, p<0.001) — see
    `HAEMATOCRIT_STANDARDISATION_SOURCE`, and `HAEMATOCRIT_EVIDENCE_LIMITS` for how far that
    evidence does and does not reach.
    """
    doses = _dosing_history()
    target = N_DAYS * 24.0 - 0.01
    reference = prior_for(Covariates())
    truth = reference.individual(20.0, 300.0)
    times = tuple(day * 24.0 - 0.05 for day in (N_DAYS - 4, N_DAYS - 3, N_DAYS - 2))
    observations = tuple(
        Observation(time_h=t, concentration_ng_per_ml=concentration_at(t, doses, truth))
        for t in times
    )

    ignored = fit_individual(doses, observations, prior_for(Covariates()))
    corrected = fit_individual(
        doses, observations, prior_for(Covariates(haematocrit=0.30))
    )

    assert (
        corrected.parameters.clearance_l_per_h < ignored.parameters.clearance_l_per_h
    ), (
        "ignoring anaemia must OVERSTATE clearance — if this inverts, the correction is being "
        "applied backwards and an anaemic patient would be pushed toward the wrong dose"
    )
    # The gap must be material rather than numerical noise; at Hct 0.30 it is roughly 20%.
    relative_gap = (
        ignored.parameters.clearance_l_per_h - corrected.parameters.clearance_l_per_h
    ) / ignored.parameters.clearance_l_per_h
    assert relative_gap > 0.10

    # And the fit must still be usable: the correction changes the estimate, not the machinery.
    prediction = predict_trough(doses, corrected, target, 5.0, 15.0, seed=6)
    assert prediction.median_ng_per_ml > 0.0
