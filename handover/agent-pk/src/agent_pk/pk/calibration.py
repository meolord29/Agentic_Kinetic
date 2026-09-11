"""calibration.py — how well this patient's own profile is resolved, and what more would buy.

This module exists to answer a question a clinician actually asks: *is this curve this patient's,
or is it still mostly the population's?* It answers in one number between 0 and 1, and it answers
a second question before any needle goes in — *what would three more samples buy?* — so that the
decision to take them is the clinician's, made on a stated expected gain, rather than the
software's.

Three design commitments, each of which is a constraint rather than a preference:

1. **The number is derived from the posterior, not from a heuristic.** It is the standard
   D-optimality information ratio between the fitted covariance and the prior it started from,
   which is a property of the fit rather than a score somebody invented.
2. **The expected gain is simulated from the CURRENT posterior**, so it is an honest forecast
   under what is believed now — not a promise, and the function name says `expected`.
3. **A model answer is cross-checked against a published equation** (`auc_cross_check`). The
   fitted curve's exposure is compared with the validated limited-sampling estimate, and a
   disagreement is surfaced rather than smoothed over. This is the deterministic check beneath
   the model, and it is what would catch our adopted structure being wrong for a given patient —
   either because absorption is parameterised differently by other published models, or because
   the three parameters held at population values cannot bend to describe this individual.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

from agent_pk.pk.fit import FitResult, fit_individual
from agent_pk.pk.model import (
    DoseEvent,
    Observation,
    PkInputError,
    _require_finite,
    auc_over_interval,
    concentration_at,
)
from agent_pk.pk.priors import PopulationPrior

logger = logging.getLogger(__name__)

# ── The validated limited-sampling equation ──────────────────────────────────

LSS_OFFSETS_H: tuple[float, float, float, float] = (0.0, 1.0, 3.0, 6.0)
"""The C0-C1-C3-C6 schedule, in hours after the dose.

THIS IS THE SCHEDULE THE AUTHORS RECOMMEND AFTER VALIDATION, and it is deliberately NOT the one
with the highest derivation R-squared. In the 2026 Frontiers in Immunology study of extended-
release tacrolimus, C0-C1-C4-C6 scores marginally higher on the derivation set (R2 0.969) but
C0-C1-C3-C6 is what survives validation (R2 0.962, RMSE 11.614 ng*h/mL, MAPE 5.464%, Kendall
tau 0.844) and is what the authors recommend. Choosing the higher derivation number would be
selecting a model by overfitting, which is precisely the error this product exists to avoid
making about an individual patient."""

_LSS_INTERCEPT = 0.57
_LSS_COEFFICIENTS: tuple[float, float, float, float] = (12.72, 1.84, 2.80, 6.79)
"""AUC0-24 = 0.57 + 12.72*C0 + 1.84*C1 + 2.80*C3 + 6.79*C6, in ng*h/mL.

Source: Frontiers in Immunology 2026, doi:10.3389/fimmu.2026.1710261.

POPULATION LIMIT, WHICH IS PART OF WHAT MUST BE SHOWN: derived in 52 Japanese kidney transplant
recipients (30 patients / 48 observations in derivation, 27 / 42 in validation) of mean weight
54-58 kg, on extended-release tacrolimus, with normal hepatic function. Applying it to a heavier
patient, another ancestry, another formulation, or impaired hepatic function is an extrapolation
and the clinician view says so where the number appears."""

LSS_POPULATION_LIMIT = (
    "Derived in 52 Japanese kidney transplant recipients (mean weight 54-58 kg) on "
    "extended-release tacrolimus with normal hepatic function. Outside that population, "
    "and for any other formulation, this equation is an extrapolation."
)

_AUC_DISAGREEMENT_TOLERANCE = 0.25
"""Fractional disagreement between the fitted and published exposure beyond which the fit is
flagged rather than trusted.

SEED-AND-MEASURE. Seeded at 25% because the published equation's own validation MAPE is ~5.5%
and this module's structural approximation is the larger of the two error sources, so a
threshold near the equation's own precision would fire constantly on structure rather than on
misfit. Erring WIDE here is NOT automatically safe — a wide tolerance misses a real structural
failure — so this is a parameter to measure against seeded fits, not to leave unexamined."""


class CalibrationError(PkInputError):
    """Raised when a calibration quantity cannot be computed from the inputs given."""


# ── Profile calibration ──────────────────────────────────────────────────────


def _prior_covariance_for(fit: FitResult, prior: PopulationPrior) -> np.ndarray:
    """The prior covariance at the same dimensionality as the fit.

    Comparing a three-parameter posterior against a two-parameter prior would compare
    determinants of different units, which is meaningless. The prior is therefore rebuilt at the
    fit's own size.
    """
    diagonal = [prior.omega_log_clearance**2, prior.omega_log_volume**2]
    if fit.estimated_ka:
        diagonal.append(prior.omega_log_ka**2)
    return np.diag(diagonal)


def profile_calibration(fit: FitResult, prior: PopulationPrior) -> float:
    """How far this patient's parameters have moved from the population, on a 0-to-1 scale.

    Zero means the fit still carries exactly the population's uncertainty — nothing individual
    has been learned. Values approaching one mean the patient's own data, not the population,
    now determines the parameters.

    **THIS NUMBER MEASURES PRECISION, NOT ACCURACY, AND IT IS NOT THE ONE TO SHOW A CLINICIAN
    ON ITS OWN.** Measured on the demo patient — a CYP3A5 expresser whose genotype was never
    tested, with a true clearance 1.62x the population prior:

        four troughs, absorption ASSUMED:   calibration 90.3%, exposure error +13.5%
        C0-C1-C3-C6, absorption ESTIMATED:  calibration 72.4%, exposure error  +1.6%

    The worse fit scores higher, and it does so for a structural reason rather than by chance: a
    two-parameter fit that assumes absorption has a tighter posterior than a three-parameter fit
    that honestly carries absorption uncertainty. Rewarding a model for having fewer parameters
    it might be wrong about is precisely backwards.

    Nothing computed from a posterior can detect its own bias — that would require knowing the
    truth. So the protection against a confidently wrong fit does not live here. It lives in
    `auc_cross_check`, which compares the fitted curve against somebody else's validated equation,
    and in `exposure_uncertainty`, which is on the same scale whatever the parameter count.

    Use this to answer "how much has this patient's own data moved the parameters"; use
    `exposure_uncertainty` to answer "how much should I trust this exposure estimate".

    The quantity is the D-optimality information ratio, normalised per parameter so that a
    two-parameter and a three-parameter fit are on the same scale:

        calibration = 1 - (det(posterior) / det(prior)) ** (1 / n)

    The n-th root matters. Without it a three-parameter fit would score differently from a
    two-parameter one for reasons of dimensionality rather than of information, and the number
    shown to a clinician would jump when the schedule changed rather than when the knowledge did.

    Args:
        fit: The individual fit.
        prior: The population prior the fit started from.

    Returns:
        A value in [0, 1]. Clamped at zero: a posterior no tighter than the prior has taught us
        nothing, and a negative "calibration" would be an unreadable way to say that.

    Raises:
        CalibrationError: If either determinant is non-finite or non-positive, which means the
            covariance is degenerate and no honest ratio can be formed.
    """
    posterior = np.asarray(fit.covariance, dtype=float)
    prior_matrix = _prior_covariance_for(fit, prior)

    posterior_det = float(np.linalg.det(posterior))
    prior_det = float(np.linalg.det(prior_matrix))
    if not (math.isfinite(posterior_det) and math.isfinite(prior_det)):
        raise CalibrationError("covariance determinant is not finite")
    if posterior_det <= 0.0 or prior_det <= 0.0:
        raise CalibrationError(
            f"covariance determinants must be positive; got posterior {posterior_det!r} "
            f"and prior {prior_det!r}"
        )

    size = len(fit.log_theta)
    ratio = (posterior_det / prior_det) ** (1.0 / size)
    return float(min(1.0, max(0.0, 1.0 - ratio)))


@dataclass(frozen=True, slots=True)
class ExposureEstimate:
    """Exposure with its credible interval — the quantity a clinician should actually read.

    Attributes:
        median_ng_h_per_ml: Posterior median exposure over the interval.
        lower_ng_h_per_ml: Lower credible bound.
        upper_ng_h_per_ml: Upper credible bound.
        credible_mass: Interval mass, e.g. 0.90.
        relative_width: (upper - lower) / median. The single number to put on screen: it is
            dimensionless, comparable between a two- and a three-parameter fit, and it does not
            improve merely because the model stopped carrying a parameter.
        independently_checkable: Whether a validated published equation could be run against
            this patient's data. FALSE for a trough-only fit — the C0-C1-C3-C6 equation needs
            post-dose concentrations that do not exist. **A confident number that nothing can
            check is the state a clinician most needs told about**, and it is the honest answer
            to "why should I ask this patient for three more samples".
    """

    median_ng_h_per_ml: float
    lower_ng_h_per_ml: float
    upper_ng_h_per_ml: float
    credible_mass: float
    relative_width: float
    independently_checkable: bool


def exposure_uncertainty(
    doses: tuple[DoseEvent, ...],
    fit: FitResult,
    *,
    start_h: float,
    end_h: float,
    seed: int,
    n_samples: int = 400,
    credible_mass: float = 0.90,
) -> ExposureEstimate:
    """Posterior exposure and its interval, by propagating the fit's own uncertainty.

    Exposure rather than a parameter, because exposure is the quantity that is compared against
    published evidence and the one a clinician reasons about. The interval is obtained the same
    way `predict_trough` obtains its own: by sampling the posterior and recomputing, so absorption
    uncertainty is carried rather than collapsed.

    Args:
        doses: Dosing history.
        fit: The individual fit.
        start_h: Interval start on the dose time axis.
        end_h: Interval end.
        seed: Explicit RNG seed.
        n_samples: Posterior draws. Fewer than `predict_trough` uses, because each draw costs a
            quadrature rather than a single evaluation.
        credible_mass: Interval mass.

    Returns:
        An ExposureEstimate.

    Raises:
        PkInputError: If any setting is a bool, non-finite, or out of range.
        CalibrationError: If too few draws were usable to form an honest interval.
    """
    _require_finite(start_h, "start_h")
    _require_finite(end_h, "end_h")
    if end_h <= start_h:
        raise PkInputError("end_h must be strictly after start_h")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise PkInputError("seed must be an int")
    if isinstance(n_samples, bool) or not isinstance(n_samples, int) or n_samples < 50:
        raise PkInputError("n_samples must be an int >= 50")
    _require_finite(credible_mass, "credible_mass")
    if not 0.5 <= credible_mass < 1.0:
        raise PkInputError("credible_mass must be in [0.5, 1.0)")

    rng = np.random.default_rng(seed)
    draws = rng.multivariate_normal(
        np.array(fit.log_theta, dtype=float),
        np.asarray(fit.covariance, dtype=float),
        size=n_samples,
    )

    values: list[float] = []
    for draw in draws:
        with np.errstate(over="ignore", under="ignore"):
            clearance = float(np.exp(draw[0]))
            volume = float(np.exp(draw[1]))
            ka = float(np.exp(draw[2])) if draw.size == 3 else fit.parameters.ka_per_h
        if not (
            math.isfinite(clearance)
            and math.isfinite(volume)
            and math.isfinite(ka)
            and clearance > 0.0
            and volume > 0.0
            and ka > 0.0
        ):
            continue
        try:
            exposure = auc_over_interval(
                start_h,
                end_h,
                doses,
                fit.parameters.with_estimates(clearance, volume, ka),
                n_points=241,
            )
        except PkInputError:
            # One unusable posterior draw, not a malformed request. Skipped like any other.
            continue
        if math.isfinite(exposure) and exposure > 0.0:
            values.append(exposure)

    if len(values) < n_samples // 2:
        raise CalibrationError(
            f"only {len(values)} of {n_samples} posterior draws produced a usable exposure; "
            f"refusing to report an interval from a degenerate sample"
        )

    array = np.asarray(values, dtype=float)
    tail = (1.0 - credible_mass) / 2.0
    lower = float(np.quantile(array, tail))
    upper = float(np.quantile(array, 1.0 - tail))
    median = float(np.median(array))
    return ExposureEstimate(
        median_ng_h_per_ml=median,
        lower_ng_h_per_ml=lower,
        upper_ng_h_per_ml=upper,
        credible_mass=credible_mass,
        relative_width=(upper - lower) / median,
        # The published equation needs C0, C1, C3 and C6. Without post-dose points there is
        # nothing to run it on, so the fit cannot be checked against anything but itself.
        independently_checkable=fit.estimated_ka,
    )


@dataclass(frozen=True, slots=True)
class SamplingOffer:
    """What a candidate sampling schedule is expected to buy, for a clinician to accept or not.

    Attributes:
        offsets_post_dose_h: The proposed draw times relative to the dose.
        n_extra_samples: How many draws beyond the trough the patient would give. This is the
            BURDEN, and it is carried alongside the gain because a clinician weighing a request
            on a patient's behalf needs both halves.
        calibration_now: The profile calibration as things stand. SECONDARY — parameter
            precision, never accuracy. See `expected_gain`.
        expected_calibration: Mean calibration across simulated futures if the schedule is taken.
        expected_gain: The calibration difference. Do NOT lead a clinician-facing card with this:
            it forecasts a RISE and then falls once real post-dose points land, because a
            three-parameter fit carries absorption uncertainty a trough-only fit assumes away.
            Pinned by `test_the_calibration_figure_can_flatter_a_worse_fit`.
        exposure_width_now: Relative width of the exposure interval as things stand.
        expected_exposure_width: Mean relative width across simulated futures if taken.
        independently_checkable_now: Whether the published equation can be run against the
            current fit. False for a trough-only fit — the honest answer to "why sample more".
        expected_independently_checkable: Whether it would become checkable if taken. True only
            when every usable simulated future was checkable.
    """

    offsets_post_dose_h: tuple[float, ...]
    n_extra_samples: int
    calibration_now: float
    expected_calibration: float
    expected_gain: float
    exposure_width_now: float
    expected_exposure_width: float
    independently_checkable_now: bool
    expected_independently_checkable: bool

    @property
    def exposure_width_gain(self) -> float:
        """How much narrower the exposure interval is expected to get, as a fraction.

        Positive means narrower. This is the number the offer card leads with, because
        `expected_gain` (calibration) is a PRECISION score that rises on the offer and then
        FALLS when the points actually land — see `profile_calibration`'s docstring. A card
        built on calibration promises a rise and delivers a drop on stage.
        """
        return self.exposure_width_now - self.expected_exposure_width


# A simulated draw time must sit within this tolerance of a delivered dose to be timed FROM it.
_DOSE_MATCH_TOLERANCE_H = 1e-6


def _validate_forecast_inputs(
    doses: tuple[DoseEvent, ...],
    next_dose_time_h: float,
    offsets_post_dose_h: tuple[float, ...],
    seed: int,
    n_simulations: int,
) -> None:
    """Reject malformed forecast inputs before any simulation runs.

    The dose-presence check is the load-bearing one and it is not defensive padding. The offsets
    are measured FROM a dose, so if `doses` contains no delivered dose at `next_dose_time_h` the
    simulation quietly models a future in which the patient never takes it: the "post-dose"
    samples land in the tail of the PREVIOUS dose, none of them is absorption-informative, every
    refit comes back trough-only, and the forecast reports a confident gain for a schedule that
    was never actually simulated. Nothing about the returned number looks wrong. Callers must
    append the scheduled dose to `doses` before forecasting, and this refuses if they have not.

    Raises:
        PkInputError: If any input is a bool, non-finite, out of range, or if no delivered dose
            sits at `next_dose_time_h`.
    """
    _require_finite(next_dose_time_h, "next_dose_time_h")
    if not offsets_post_dose_h:
        raise PkInputError("offsets_post_dose_h must not be empty")
    for index, offset in enumerate(offsets_post_dose_h):
        _require_finite(offset, f"offsets_post_dose_h[{index}]")
        if offset < 0.0:
            raise PkInputError("offsets_post_dose_h must not be negative")
    # An offset of exactly 0.0 is the trough that is already scheduled, and an observation AT a
    # dose time is never absorption-informative (`0.0 < elapsed` in fit.py). A schedule of
    # troughs alone is therefore not an offer: it asks the patient for nothing and can never
    # make the fit checkable, while still returning a confident-looking forecast.
    if not any(offset > 0.0 for offset in offsets_post_dose_h):
        raise PkInputError(
            "offsets_post_dose_h must contain at least one draw after the dose: a schedule of "
            "troughs alone asks the patient for nothing and can never identify absorption"
        )
    # bool is rejected FIRST and by type: bool subclasses int, so True would pass both the
    # isinstance check and the range check below, and silently become a seed of 1.
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise PkInputError("seed must be an int")
    if (
        isinstance(n_simulations, bool)
        or not isinstance(n_simulations, int)
        or n_simulations < 1
    ):
        raise PkInputError("n_simulations must be an int >= 1")

    if not any(
        dose.delivered_mg > 0.0
        and abs(dose.time_h - next_dose_time_h) <= _DOSE_MATCH_TOLERANCE_H
        for dose in doses
    ):
        raise PkInputError(
            f"no delivered dose at next_dose_time_h={next_dose_time_h}: the offsets are "
            "measured from a dose, so the scheduled dose must be present in `doses` or the "
            "forecast silently simulates a future in which the patient never takes it"
        )


def _simulated_refits(
    doses: tuple[DoseEvent, ...],
    fit: FitResult,
    prior: PopulationPrior,
    *,
    existing_observations: tuple[Observation, ...],
    next_dose_time_h: float,
    offsets_post_dose_h: tuple[float, ...],
    seed: int,
    n_simulations: int,
) -> Iterator[FitResult]:
    """Yield refits of futures drawn FROM THE CURRENT POSTERIOR.

    Shared by every `expected_*_after` forecaster so they simulate identically and a change to
    the simulation cannot silently apply to one of them and not the other. A parameter vector is
    drawn, concentrations at the proposed times are generated from it with the prior's residual
    error, and the fit is repeated on the AUGMENTED data — the patient's existing observations
    plus the simulated ones.

    `existing_observations` is required, not defaulted, and that is the whole point of the
    parameter. `FitResult` does not carry the observations it was made from, so an earlier
    version refit on the simulated points ALONE — discarding the patient's history. It therefore
    forecast a different fit from the one the clinician would actually get: measured on the demo
    patient, a forecast width of 0.264 against a realised 0.211, and a calibration direction that
    flipped with the seed. A default of `()` would have reproduced that silently.

    An individual draw that lands in an unusable corner of the posterior is SKIPPED rather than
    raised: it is one draw, not a failure of the forecast. A caller that receives no refits at
    all is looking at a different statement and must refuse rather than report a zero.

    Args:
        doses: Dosing history, including the dose the samples are timed from.
        fit: The current fit, whose covariance is the posterior sampled from.
        prior: The population prior, for its residual error model.
        existing_observations: The observations `fit` was made from. Carried into every refit,
            because the clinician keeps them — they do not vanish when new samples arrive.
        next_dose_time_h: The dose the offsets are measured from.
        offsets_post_dose_h: Candidate draw times relative to that dose.
        seed: Explicit RNG seed. There is no implicit randomness in this module.
        n_simulations: Futures to attempt.

    Yields:
        One `FitResult` per usable simulated future.
    """
    rng = np.random.default_rng(seed)
    mean = np.array(fit.log_theta, dtype=float)
    covariance = np.asarray(fit.covariance, dtype=float)
    draws = rng.multivariate_normal(mean, covariance, size=n_simulations)
    sigma = prior.proportional_residual_cv

    for draw in draws:
        with np.errstate(over="ignore", under="ignore"):
            clearance = float(np.exp(draw[0]))
            volume = float(np.exp(draw[1]))
            ka = float(np.exp(draw[2])) if draw.size == 3 else fit.parameters.ka_per_h
        if not (
            math.isfinite(clearance)
            and math.isfinite(volume)
            and math.isfinite(ka)
            and clearance > 0.0
            and volume > 0.0
            and ka > 0.0
        ):
            continue

        try:
            truth = prior.individual(clearance, volume, ka)
        except PkInputError:
            continue
        simulated = []
        for offset in offsets_post_dose_h:
            time_h = next_dose_time_h + offset
            value = concentration_at(time_h, doses, truth)
            noisy = value * (1.0 + sigma * float(rng.standard_normal()))
            if not math.isfinite(noisy) or noisy <= 0.0:
                continue
            simulated.append(Observation(time_h, noisy))
        if not simulated:
            continue

        try:
            yield fit_individual(doses, (*existing_observations, *simulated), prior)
        except (PkInputError, CalibrationError):
            # A single unusable simulated future is not a failure of the forecast; it is one
            # draw from a corner of the posterior. It is skipped and the remainder averaged.
            # If EVERY future is unusable that is a different statement, made by the caller.
            logger.debug(
                "a simulated future produced no usable fit; skipping that draw"
            )
            continue


def expected_calibration_after(
    doses: tuple[DoseEvent, ...],
    fit: FitResult,
    prior: PopulationPrior,
    *,
    existing_observations: tuple[Observation, ...],
    next_dose_time_h: float,
    offsets_post_dose_h: tuple[float, ...],
    seed: int,
    n_simulations: int = 24,
) -> float:
    """Forecast the profile calibration if a candidate schedule were taken.

    This is an expectation under what is believed now — honest, and not a promise. If the
    patient's true parameters lie outside the current posterior, the realised gain will differ.

    NOTE FOR CALLERS BUILDING A CLINICIAN-FACING CARD: this figure is PARAMETER PRECISION, and
    `profile_calibration`'s own docstring records that it can be HIGHER on a worse fit. It rises
    in this forecast and then falls when real post-dose points land, because a three-parameter
    fit carries absorption uncertainty that a trough-only fit assumes away. Lead the card with
    `expected_exposure_width_after` instead. See `SamplingOffer.exposure_width_gain`.

    Args:
        doses: Dosing history, including the dose the samples are timed from.
        fit: The current fit.
        prior: The population prior.
        existing_observations: The observations `fit` was made from — REQUIRED, and carried into
            every simulated refit. See `_simulated_refits` for why this may not default to empty.
        next_dose_time_h: The dose the offsets are measured from.
        offsets_post_dose_h: Candidate draw times relative to that dose.
        seed: Explicit RNG seed. There is no implicit randomness in this module.
        n_simulations: Futures to average over.

    Returns:
        Mean expected profile calibration in [0, 1].

    Raises:
        PkInputError: If any input is a bool, non-finite, or out of range.
        CalibrationError: If no simulated future produced a usable fit.
    """
    _validate_forecast_inputs(
        doses, next_dose_time_h, offsets_post_dose_h, seed, n_simulations
    )
    calibrations = [
        profile_calibration(refit, prior)
        for refit in _simulated_refits(
            doses,
            fit,
            prior,
            existing_observations=existing_observations,
            next_dose_time_h=next_dose_time_h,
            offsets_post_dose_h=offsets_post_dose_h,
            seed=seed,
            n_simulations=n_simulations,
        )
    ]
    if not calibrations:
        raise CalibrationError(
            "no simulated future produced a usable fit, so no expected calibration can be "
            "reported — this is a refusal, not a gain of zero"
        )
    return float(np.mean(calibrations))


def expected_exposure_width_after(
    doses: tuple[DoseEvent, ...],
    fit: FitResult,
    prior: PopulationPrior,
    *,
    existing_observations: tuple[Observation, ...],
    next_dose_time_h: float,
    offsets_post_dose_h: tuple[float, ...],
    start_h: float,
    end_h: float,
    seed: int,
    n_simulations: int = 24,
    n_samples_per_future: int = 64,
) -> tuple[float, bool]:
    """Forecast the EXPOSURE interval width if a candidate schedule were taken.

    This is the honest counterpart to `expected_calibration_after`, and it is the figure a
    clinician-facing sampling offer must lead with. Calibration measures how precisely the
    PARAMETERS are pinned and is higher on a fit that assumes absorption away; exposure width
    measures how uncertain the quantity a clinician actually reasons about is, carrying
    absorption uncertainty rather than discarding it. The two move in opposite directions when
    post-dose points land, which is why the distinction is load-bearing rather than cosmetic.

    Simulation is shared with `expected_calibration_after` via `_simulated_refits`, so the two
    forecasts describe the same futures.

    Args:
        doses: Dosing history, including the dose the samples are timed from.
        fit: The current fit.
        prior: The population prior.
        existing_observations: The observations `fit` was made from — REQUIRED, and carried into
            every simulated refit. See `_simulated_refits` for why this may not default to empty.
        next_dose_time_h: The dose the offsets are measured from.
        offsets_post_dose_h: Candidate draw times relative to that dose.
        start_h: Exposure interval start on the dose time axis.
        end_h: Exposure interval end. Must be after `start_h`.
        seed: Explicit RNG seed. There is no implicit randomness in this module.
        n_simulations: Futures to average over.
        n_samples_per_future: Posterior samples drawn per simulated future. Deliberately far
            below `exposure_uncertainty`'s own default: the outer mean over `n_simulations`
            futures already does the variance reduction, and the product of the two defaults is
            what a clinician waits through while the offer card renders.

    Returns:
        `(mean expected relative width, whether the refit becomes independently checkable)`.
        The flag is True only when EVERY usable simulated future could be checked against the
        published equation, so a partial answer never advertises itself as a checkable one — AND
        only when the offered schedule actually contains the LSS times the equation consumes.
        Absorption being identifiable is not the same as the cross-check being runnable: any two
        points inside the absorption window identify ka, while `published_auc_from_curve` needs
        C0, C1, C3 and C6 specifically.

    Raises:
        PkInputError: If any input is a bool, non-finite, or out of range.
        CalibrationError: If no simulated future produced a usable exposure estimate.
    """
    _validate_forecast_inputs(
        doses, next_dose_time_h, offsets_post_dose_h, seed, n_simulations
    )
    _require_finite(start_h, "start_h")
    _require_finite(end_h, "end_h")
    if end_h <= start_h:
        raise PkInputError("end_h must be after start_h")
    if (
        isinstance(n_samples_per_future, bool)
        or not isinstance(n_samples_per_future, int)
        or n_samples_per_future < 2
    ):
        raise PkInputError("n_samples_per_future must be an int >= 2")

    # `estimated_ka` only says absorption was identifiable, which any two points inside the
    # 8 h window achieve. The published equation needs the LSS schedule specifically, so a
    # schedule of (0, 2, 4) would otherwise promise a cross-check that cannot be run.
    carries_lss_schedule = all(
        any(
            abs(offset - required) <= _DOSE_MATCH_TOLERANCE_H
            for offset in offsets_post_dose_h
        )
        for required in LSS_OFFSETS_H
    )

    widths: list[float] = []
    checkable: list[bool] = []
    for index, refit in enumerate(
        _simulated_refits(
            doses,
            fit,
            prior,
            existing_observations=existing_observations,
            next_dose_time_h=next_dose_time_h,
            offsets_post_dose_h=offsets_post_dose_h,
            seed=seed,
            n_simulations=n_simulations,
        )
    ):
        try:
            estimate = exposure_uncertainty(
                doses,
                refit,
                start_h=start_h,
                end_h=end_h,
                # Derived from the caller's seed so the whole forecast stays reproducible,
                # while each future draws its own posterior samples rather than reusing one.
                seed=seed + 1 + index,
                n_samples=n_samples_per_future,
            )
        except (PkInputError, CalibrationError):
            logger.debug(
                "a simulated future produced no usable exposure estimate; skipping"
            )
            continue
        # A non-finite width would silently satisfy any downstream `width < threshold` guard,
        # because every ordered comparison against NaN is False. It never enters the mean.
        if not math.isfinite(estimate.relative_width):
            logger.debug(
                "a simulated future produced a non-finite exposure width; skipping"
            )
            continue
        widths.append(estimate.relative_width)
        checkable.append(estimate.independently_checkable and carries_lss_schedule)

    if not widths:
        raise CalibrationError(
            "no simulated future produced a usable exposure estimate, so no expected width "
            "can be reported — this is a refusal, not a width of zero, which would read as "
            "perfect certainty"
        )
    return float(np.mean(widths)), all(checkable)


def build_sampling_offer(
    doses: tuple[DoseEvent, ...],
    fit: FitResult,
    prior: PopulationPrior,
    *,
    existing_observations: tuple[Observation, ...],
    next_dose_time_h: float,
    offsets_post_dose_h: tuple[float, ...] = LSS_OFFSETS_H,
    exposure_window_h: float = 24.0,
    seed: int,
    n_simulations: int = 24,
) -> SamplingOffer:
    """Assemble the offer a clinician accepts or declines.

    The burden is counted as the draws BEYOND the trough, because a trough is already scheduled
    and the marginal ask is what the patient actually experiences as extra.

    The offer carries BOTH scores deliberately. `exposure_width_*` is what the card leads with:
    it is the uncertainty in the quantity a clinician reasons about, and it genuinely improves
    when post-dose points land. `calibration_*` is retained as a secondary "how individualised
    is this profile" indicator and must never be presented as accuracy — it can rise in the
    forecast and fall in reality, which on stage reads as the tool getting worse.

    Args:
        doses: Dosing history, including the dose the samples are timed from.
        fit: The current fit.
        prior: The population prior.
        existing_observations: The observations `fit` was made from — REQUIRED, and carried into
            every simulated refit. See `_simulated_refits` for why this may not default to empty.
        next_dose_time_h: The dose the offsets are measured from.
        offsets_post_dose_h: Candidate draw times relative to that dose.
        exposure_window_h: Length of the exposure interval scored, from `next_dose_time_h`.
            **Defaults to 24 h, which is one ONCE-DAILY dosing interval and is the formulation
            this build commits to.** It is not inferred from the dosing history: a caller on a
            twice-daily schedule who does not override it scores a window covering two doses.
            Pass it explicitly for any non-QD regimen.
        seed: Explicit RNG seed. There is no implicit randomness in this module.
        n_simulations: Futures to average over.

    Returns:
        The `SamplingOffer` a clinician accepts or declines.

    Raises:
        PkInputError: If any input is a bool, non-finite, or out of range.
        CalibrationError: If no simulated future produced a usable fit or exposure estimate.
    """
    _require_finite(exposure_window_h, "exposure_window_h")
    if exposure_window_h <= 0.0:
        raise PkInputError("exposure_window_h must be positive")
    now = profile_calibration(fit, prior)
    expected = expected_calibration_after(
        doses,
        fit,
        prior,
        existing_observations=existing_observations,
        next_dose_time_h=next_dose_time_h,
        offsets_post_dose_h=offsets_post_dose_h,
        seed=seed,
        n_simulations=n_simulations,
    )
    current_exposure = exposure_uncertainty(
        doses,
        fit,
        start_h=next_dose_time_h,
        end_h=next_dose_time_h + exposure_window_h,
        # Offset from the forecast's own stream. Both sample the SAME posterior, so sharing a
        # seed makes the simulated "truth" draws literally the leading draws of the current
        # estimate. Harmless here, but the two halves of a comparison should not be correlated
        # by construction.
        seed=seed + n_simulations + 1,
    )
    expected_width, expected_checkable = expected_exposure_width_after(
        doses,
        fit,
        prior,
        existing_observations=existing_observations,
        next_dose_time_h=next_dose_time_h,
        offsets_post_dose_h=offsets_post_dose_h,
        start_h=next_dose_time_h,
        end_h=next_dose_time_h + exposure_window_h,
        seed=seed,
        n_simulations=n_simulations,
    )
    # The forecast skips non-finite simulated widths; the CURRENT width was previously
    # assembled unguarded, so a NaN here would become the card's headline number and would
    # silently satisfy every downstream `width < threshold` comparison.
    if not math.isfinite(current_exposure.relative_width):
        raise CalibrationError(
            "the current exposure width is not finite, so no offer can be assembled — this is "
            "a refusal, not a width of zero, which would read as perfect certainty"
        )
    extra = sum(1 for offset in offsets_post_dose_h if offset > 0.0)
    return SamplingOffer(
        offsets_post_dose_h=tuple(offsets_post_dose_h),
        n_extra_samples=extra,
        calibration_now=now,
        expected_calibration=expected,
        expected_gain=expected - now,
        exposure_width_now=current_exposure.relative_width,
        expected_exposure_width=expected_width,
        independently_checkable_now=current_exposure.independently_checkable,
        expected_independently_checkable=expected_checkable,
    )


# ── The independent cross-check ──────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AucCrossCheck:
    """The fitted exposure set beside the published estimate, and whether they agree.

    Attributes:
        model_auc: Exposure from integrating the fitted individual curve.
        published_auc: Exposure from the validated limited-sampling equation.
        relative_disagreement: Signed fraction, (model - published) / published.
        agrees: Whether the disagreement is inside tolerance. FALSE IS NOT AN ERROR — it is a
            finding, and it means the interval should be widened and the fit treated with
            suspicion rather than reported as though it were confirmed.
        population_limit: The equation's own population limit, carried so it cannot be shown
            without it.
    """

    model_auc: float
    published_auc: float
    relative_disagreement: float
    agrees: bool
    population_limit: str = LSS_POPULATION_LIMIT


def published_auc_from_curve(
    concentrations: tuple[float, float, float, float],
) -> float:
    """Exposure over 24 hours from the validated C0-C1-C3-C6 equation.

    Args:
        concentrations: Measured ng/mL at 0, 1, 3 and 6 hours after the dose, in that order.

    Returns:
        AUC0-24 in ng*h/mL.

    Raises:
        PkInputError: If any concentration is a bool, non-finite, or not positive.
    """
    if len(concentrations) != 4:
        raise PkInputError(
            f"the C0-C1-C3-C6 equation needs exactly 4 concentrations, got "
            f"{len(concentrations)}"
        )
    total = _LSS_INTERCEPT
    for index, (value, coefficient) in enumerate(
        zip(concentrations, _LSS_COEFFICIENTS, strict=True)
    ):
        _require_finite(value, f"concentrations[{index}]")
        if value <= 0.0:
            raise PkInputError(
                f"concentrations[{index}] must be positive, got {value!r}"
            )
        total += coefficient * value
    return total


def auc_cross_check(
    doses: tuple[DoseEvent, ...],
    fit: FitResult,
    *,
    dose_time_h: float,
    measured_curve: tuple[float, float, float, float],
    tolerance: float = _AUC_DISAGREEMENT_TOLERANCE,
) -> AucCrossCheck:
    """Compare the fitted individual curve's exposure against the published equation's.

    This is the deterministic check beneath the model. The fitted curve is ours; the equation is
    somebody else's, validated in real patients. When they disagree materially, the most likely
    explanation is not that the patient is unusual but that our STRUCTURE is wrong for them.
    Extended-release absorption is parameterised differently across published models — two gamma
    distributions in Riff et al. (2019), the delayed first-order rate this model adopts from
    Fernandez-Alarcon et al. (2024) — and three of our six parameters are held at population
    values, so a genuinely atypical distribution has no way to show itself in the fitted curve.

    Args:
        doses: Dosing history.
        fit: The individual fit whose curve is being checked.
        dose_time_h: The dose the measured curve was timed from.
        measured_curve: The MEASURED concentrations at C0, C1, C3, C6. Measured, not predicted —
            feeding the model's own predictions into the equation would compare the model with
            itself, which is the "replayed input satisfies the gate it feeds" failure and would
            make this check decorative.
        tolerance: Fractional disagreement treated as agreement.

    Returns:
        An AucCrossCheck. Disagreement is reported, never raised: it is a finding for a clinician,
        not a crash.

    Raises:
        PkInputError: If any input is malformed, or the tolerance is not a positive fraction.
    """
    _require_finite(dose_time_h, "dose_time_h")
    _require_finite(tolerance, "tolerance")
    if not 0.0 < tolerance < 1.0:
        raise PkInputError(f"tolerance must be in (0, 1), got {tolerance!r}")

    published = published_auc_from_curve(measured_curve)
    model = auc_over_interval(dose_time_h, dose_time_h + 24.0, doses, fit.parameters)

    if published <= 0.0:
        raise PkInputError("the published equation returned a non-positive exposure")
    disagreement = (model - published) / published
    return AucCrossCheck(
        model_auc=model,
        published_auc=published,
        relative_disagreement=disagreement,
        agrees=abs(disagreement) <= tolerance,
    )
