"""model.py — two-compartment, delayed-first-order-absorption tacrolimus PK.

Structural model only. No fitting, no priors, no policy.

The structure is the published one (see `priors.py`): two compartments with a first-order
absorption that begins only after a lag. It is NOT a modelling convenience — the parameter
estimates this project uses were fitted to this structure, and estimates are conditional on
the model that produced them, so borrowing the numbers into a simpler form would produce
values that looked sourced and were not.

Units are fixed and asserted in the test suite:
    dose        mg
    clearance   L/h   (apparent, CL/F — bioavailability is folded in)
    volumes     L     (apparent, Vc/F central and Vp/F peripheral)
    CLD         L/h   (apparent, CLD/F — intercompartmental distribution clearance)
    ka          1/h
    lag         h
    time        hours since a per-patient reference instant
    output      ng/mL (whole blood)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

# ── Constants ────────────────────────────────────────────────────────────────

MG_PER_L_TO_NG_PER_ML = 1000.0
"""1 mg/L == 1000 ng/mL. Applied once, here, and nowhere else."""

_MIN_RELATIVE_RATE_GAP = 1e-3
"""Below this |ka - ke| / max(ka, ke), the direct difference form is never used.

Branching on |x| alone was insufficient: with ka and ke nearly equal but the elapsed time very
large, |x| exceeds the overflow threshold while (ka - ke) is still tiny, so the direct form
subtracts two near-equal numbers and cancels. The damping form is used there instead — and it
cannot overflow there, because reaching |x| > 500 with a relative gap below 1e-3 requires
k*t > 5e5, which makes both exponentials underflow and the preceding zero guard fire first.

ON THE VERIFIER'S WITNESS (ka=0.0500, ke=0.0499, t=6e6 h), corrected by the second seat: its
relative gap is 0.002, which is ABOVE this threshold, so that particular case is decided by the
underflow guard rather than by this constant. The concern it illustrates is real and this
constant answers it; the witness simply exercises a different guard. Recorded rather than
quietly fixed, because a comment that misdescribes which branch runs is how the next reader
draws the wrong conclusion."""

_MAX_EXP_ARG = 500.0
"""Beyond this |x| the expm1 form would overflow, so the direct difference form is used instead.

The two forms are complementary and leave NO precision gap: cancellation between the two
exponentials only matters when |x| is SMALL, and overflow of expm1 only happens when |x| is
LARGE. Found by this module's own degenerate-sampling test, which draws absurd parameters on
purpose — the first expm1-only revision raised OverflowError from inside the sampler."""

_EXPM1_SERIES_TOL = 1e-8
"""Below this |x| the ratio -expm1(-x)/x is evaluated by its two-term series, 1 - x/2.

There is no longer a separate ka==ke branch to tune. The concentration is computed in a form
whose singularity is REMOVED rather than special-cased, so precision no longer depends on
choosing the right width for a band. See _damping_ratio."""

DoseStatus = Literal["taken", "missed", "vomited"]
"""A dose the patient reports. 'missed' and 'vomited' both deliver nothing to the systemic
circulation — the distinction is kept because it matters clinically and to the audit trail,
not because the model treats them differently."""


class PkInputError(ValueError):
    """Raised when a PK input is malformed, non-finite, or outside its physical range."""


# ── Types ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PkParameters:
    """Individual apparent PK parameters for a TWO-COMPARTMENT model with delayed absorption.

    The structure is the published one, not a convenience: prolonged-release tacrolimus is
    described in the literature by two compartments with a delayed first-order absorption, and
    an earlier revision of this module used one compartment with a single first-order rate and
    no lag. That structure matched no published model, so its parameters could not be sourced
    from one and were invented to fit it. This one carries the estimates of a named model
    (see `priors.py`), which is only meaningful because the structure matches too.

    Attributes:
        clearance_l_per_h: CL/F, apparent elimination clearance from the central compartment.
        volume_central_l: Vc/F, apparent central volume.
        volume_peripheral_l: Vp/F, apparent peripheral volume.
        intercompartmental_clearance_l_per_h: CLD/F, apparent distribution clearance between
            the central and peripheral compartments.
        ka_per_h: First-order absorption rate constant.
        lag_h: Absorption lag. No drug is absorbed before it elapses.
    """

    clearance_l_per_h: float
    volume_central_l: float
    volume_peripheral_l: float
    intercompartmental_clearance_l_per_h: float
    ka_per_h: float
    lag_h: float

    def __post_init__(self) -> None:
        for name, value in (
            ("clearance_l_per_h", self.clearance_l_per_h),
            ("volume_central_l", self.volume_central_l),
            ("volume_peripheral_l", self.volume_peripheral_l),
            (
                "intercompartmental_clearance_l_per_h",
                self.intercompartmental_clearance_l_per_h,
            ),
            ("ka_per_h", self.ka_per_h),
        ):
            _require_positive_finite(value, name)
        _require_non_negative_finite(self.lag_h, "lag_h")

    def with_estimates(
        self,
        clearance_l_per_h: float,
        volume_central_l: float,
        ka_per_h: float | None = None,
    ) -> PkParameters:
        """The same FIXED disposition parameters, with the estimated ones replaced.

        Posterior sampling varies only the parameters the fit estimated; Vp/F, CLD/F and the lag
        are population constants and must come through unchanged. Taking them from THIS object
        rather than from a prior matters at the two call sites that have a fit but no prior in
        scope: the parameters a sample is drawn around have to be the ones the fit was built
        with, not a prior's, or the sample would be drawn around a different curve than the mode.

        Args:
            clearance_l_per_h: The sampled CL/F.
            volume_central_l: The sampled Vc/F.
            ka_per_h: The sampled absorption rate, or None to keep this object's.

        Returns:
            A new `PkParameters` sharing this one's fixed disposition values.
        """
        return PkParameters(
            clearance_l_per_h=clearance_l_per_h,
            volume_central_l=volume_central_l,
            volume_peripheral_l=self.volume_peripheral_l,
            intercompartmental_clearance_l_per_h=(
                self.intercompartmental_clearance_l_per_h
            ),
            ka_per_h=self.ka_per_h if ka_per_h is None else ka_per_h,
            lag_h=self.lag_h,
        )

    @property
    def k10_per_h(self) -> float:
        """Elimination rate constant from the central compartment, CL/Vc."""
        return self.clearance_l_per_h / self.volume_central_l

    @property
    def k12_per_h(self) -> float:
        """Central-to-peripheral distribution rate constant, CLD/Vc."""
        return self.intercompartmental_clearance_l_per_h / self.volume_central_l

    @property
    def k21_per_h(self) -> float:
        """Peripheral-to-central distribution rate constant, CLD/Vp."""
        return self.intercompartmental_clearance_l_per_h / self.volume_peripheral_l

    @property
    def disposition_rates_per_h(self) -> tuple[float, float]:
        """The fast and slow disposition eigenvalues, (alpha, beta), with alpha > beta.

        Roots of `lambda**2 - (k12 + k21 + k10) * lambda + k21 * k10 = 0`.

        The discriminant is STRICTLY positive whenever k12 > 0, so the two rates never
        coincide and the `(alpha - beta)` denominators in the concentration expression cannot
        vanish. Proof, because a reader should not have to take it on trust: writing
        `s = k12 + k21 + k10`, the discriminant is `s**2 - 4*k21*k10`, and `s > k21 + k10`
        whenever k12 > 0, so `s**2 > (k21 + k10)**2 = (k21 - k10)**2 + 4*k21*k10 >= 4*k21*k10`.
        The constructor already requires CLD/F positive, which makes k12 positive.

        Returns:
            `(alpha, beta)` in per-hour, alpha strictly greater than beta.

        Raises:
            PkInputError: If the discriminant is not positive, which the proof above says is
                unreachable — so it is raised rather than clamped, because reaching it means an
                assumption has broken rather than that a value needs nudging.
        """
        k10 = self.k10_per_h
        k12 = self.k12_per_h
        k21 = self.k21_per_h
        total = k12 + k21 + k10
        discriminant = total * total - 4.0 * k21 * k10
        if not math.isfinite(discriminant) or discriminant <= 0.0:
            raise PkInputError(
                f"disposition discriminant is not positive ({discriminant!r}); the two "
                "disposition rates would coincide, which positive CLD/F should make impossible"
            )
        root = math.sqrt(discriminant)
        return (total + root) / 2.0, (total - root) / 2.0


@dataclass(frozen=True, slots=True)
class DoseEvent:
    """One scheduled dose and what the patient reports happened to it."""

    time_h: float
    amount_mg: float
    status: DoseStatus = "taken"

    def __post_init__(self) -> None:
        _require_finite(self.time_h, "time_h")
        _require_non_negative_finite(self.amount_mg, "amount_mg")
        if self.status not in ("taken", "missed", "vomited"):
            raise PkInputError(f"unknown dose status: {self.status!r}")

    @property
    def delivered_mg(self) -> float:
        """Drug actually reaching absorption. Zero unless the dose was taken and kept down."""
        return self.amount_mg if self.status == "taken" else 0.0


@dataclass(frozen=True, slots=True)
class Observation:
    """One measured whole-blood concentration from a laboratory report."""

    time_h: float
    concentration_ng_per_ml: float

    def __post_init__(self) -> None:
        _require_finite(self.time_h, "time_h")
        _require_positive_finite(
            self.concentration_ng_per_ml, "concentration_ng_per_ml"
        )


# ── Validation helpers ───────────────────────────────────────────────────────


def _require_finite(value: float, name: str) -> None:
    """Reject bool, non-numeric and non-finite values.

    ``bool`` is rejected by type before any numeric test, because ``True`` passes
    ``isinstance(x, int)`` and every subsequent comparison. Non-finite values are rejected
    because every ordered comparison against NaN evaluates False, which would make a
    downstream boundary check silently fail open.

    Raises:
        PkInputError: If value is a bool, not a real number, or not finite.
    """
    if isinstance(value, bool):
        raise PkInputError(f"{name} must be a real number, not a bool")
    if not isinstance(value, (int, float)):
        raise PkInputError(f"{name} must be a real number, got {type(value).__name__}")
    if not math.isfinite(value):
        raise PkInputError(f"{name} must be finite, got {value!r}")


def _require_non_negative_finite(value: float, name: str) -> None:
    """Raise PkInputError unless value is finite and >= 0."""
    _require_finite(value, name)
    if value < 0.0:
        raise PkInputError(f"{name} must be >= 0, got {value!r}")


def _require_positive_finite(value: float, name: str) -> None:
    """Raise PkInputError unless value is finite and > 0."""
    _require_finite(value, name)
    if value <= 0.0:
        raise PkInputError(f"{name} must be > 0, got {value!r}")


# ── Core structural model ────────────────────────────────────────────────────


def _damping_ratio(x: float) -> float:
    """(1 - exp(-x)) / x, evaluated stably, with its removable singularity handled.

    Equals 1.0 in the limit x -> 0. Computed with ``expm1`` so that small x does not lose
    precision to catastrophic cancellation between two nearly-equal exponentials.

    Args:
        x: The dimensionless product (ka - ke) * elapsed time. May be any sign.

    Returns:
        The ratio, which is 1.0 at x == 0 and positive for all real x.
    """
    if abs(x) < _EXPM1_SERIES_TOL:
        # Second-order series: (1 - exp(-x))/x = 1 - x/2 + x^2/6 - ...
        return 1.0 - x / 2.0
    return -math.expm1(-x) / x


def _exp_difference_over_gap(
    rate_per_h: float, ka_per_h: float, elapsed_h: float
) -> float:
    """`(exp(-rate*t) - exp(-ka*t)) / (ka - rate)`, evaluated stably.

    This is the one numerically delicate quantity in the two-compartment oral solution, and it
    appears TWICE — once against each disposition rate. Factoring it out means the removable
    singularity at `ka == rate` is handled in exactly one place for both, rather than in two
    places that could drift apart.

    The identity used is `(exp(-r*t) - exp(-ka*t)) / (ka - r) == t * exp(-r*t) * D((ka - r)*t)`
    where `D` is `_damping_ratio`, which tends to 1 as its argument tends to zero. So the
    singularity is REMOVED rather than special-cased with a tolerance band — the same treatment
    a verifier forced on the one-compartment form, and for the same reason: just outside any
    band, the divide-by-`(ka - r)` form still cancels catastrophically.

    Args:
        rate_per_h: A disposition rate (alpha or beta).
        ka_per_h: The absorption rate constant.
        elapsed_h: Hours since absorption began. Must be non-negative.

    Returns:
        The difference quotient, in hours.
    """
    # Both exponentials underflow to exactly zero, so the quotient IS zero in double precision.
    if rate_per_h * elapsed_h > _MAX_EXP_ARG and ka_per_h * elapsed_h > _MAX_EXP_ARG:
        return 0.0

    x = (ka_per_h - rate_per_h) * elapsed_h
    relative_gap = abs(ka_per_h - rate_per_h) / max(ka_per_h, rate_per_h)

    if abs(x) > _MAX_EXP_ARG and relative_gap > _MIN_RELATIVE_RATE_GAP:
        # Well separated, so one exponential is negligible beside the other and the direct
        # difference cannot cancel. Both terms are exp of a non-positive argument.
        difference = math.exp(-rate_per_h * elapsed_h) - math.exp(-ka_per_h * elapsed_h)
        return difference / (ka_per_h - rate_per_h)

    return elapsed_h * math.exp(-rate_per_h * elapsed_h) * _damping_ratio(x)


def _single_dose_concentration_mg_per_l(
    dose_mg: float, elapsed_h: float, params: PkParameters
) -> float:
    """Two-compartment oral concentration for one dose, in mg/L.

    Returns 0.0 before absorption begins, which is the dose time PLUS the lag.

    The textbook form is a sum of three exponentials whose coefficients each carry a
    `(ka - alpha)` or `(ka - beta)` denominator. Written that way it has two singularities and
    two chances to cancel catastrophically. Because the three coefficients sum to zero — which
    they must, since the concentration is zero at t=0 for an oral dose — the `exp(-ka*t)` term
    can be folded into the other two, leaving a sum of exactly two difference quotients:

        C = (D * ka / Vc) * [ (k21 - alpha)/(beta - alpha) * E(alpha)
                            + (k21 - beta)/(alpha - beta)  * E(beta)  ]

    where `E(r)` is `_exp_difference_over_gap(r, ka, t)`. Both singularities are then removed by
    the same helper, and the `(alpha - beta)` denominator cannot vanish (see
    `PkParameters.disposition_rates_per_h`).

    Args:
        dose_mg: Amount delivered to absorption.
        elapsed_h: Hours since the dose was taken. Negative means it has not been given.
        params: Individual PK parameters.

    Returns:
        Concentration contribution in mg/L.
    """
    if dose_mg <= 0.0:
        return 0.0

    absorbing_h = elapsed_h - params.lag_h
    if absorbing_h < 0.0:
        return 0.0

    ka = params.ka_per_h
    k21 = params.k21_per_h
    alpha, beta = params.disposition_rates_per_h
    gap = alpha - beta

    contribution = (k21 - alpha) / (-gap) * _exp_difference_over_gap(
        alpha, ka, absorbing_h
    ) + (k21 - beta) / gap * _exp_difference_over_gap(beta, ka, absorbing_h)

    return (dose_mg * ka / params.volume_central_l) * contribution


def auc_over_interval(
    start_h: float,
    end_h: float,
    doses: tuple[DoseEvent, ...],
    params: PkParameters,
    *,
    n_points: int = 1201,
) -> float:
    """Area under the concentration-time curve over an interval, by trapezoidal quadrature.

    EXPOSURE, not a single concentration, is the quantity the limited-sampling literature
    validates against and the one a clinician reasons about. A trough is one point on a curve;
    two patients with the same trough can carry materially different exposure.

    Quadrature rather than a closed form on purpose: the closed form for a one-compartment model
    at steady state is Dose/CL, which is exact only once the system HAS reached steady state and
    only if every dose was delivered. Integrating the actual superposed curve stays correct
    through a missed dose, a dose change, and the days before steady state — which is most of
    what this product looks at.

    Args:
        start_h: Interval start, on the dose time axis.
        end_h: Interval end. Must be strictly after start_h.
        doses: The patient's dosing history.
        params: Individual PK parameters.
        n_points: Quadrature points. The default resolves the concentration curve over a
            24-hour interval to well below the assay's own error.

    Returns:
        Exposure in ng*h/mL.

    Raises:
        PkInputError: If either bound is a bool or non-finite, the interval is not positive, or
            n_points is not an int of at least 2.
    """
    _require_finite(start_h, "start_h")
    _require_finite(end_h, "end_h")
    if end_h <= start_h:
        raise PkInputError(
            f"end_h ({end_h!r}) must be strictly after start_h ({start_h!r})"
        )
    if isinstance(n_points, bool) or not isinstance(n_points, int) or n_points < 2:
        raise PkInputError("n_points must be an int >= 2")

    step = (end_h - start_h) / (n_points - 1)
    total = 0.0
    previous = concentration_at(start_h, doses, params)
    for index in range(1, n_points):
        current = concentration_at(start_h + index * step, doses, params)
        total += 0.5 * (previous + current) * step
        previous = current
    return total


def concentration_at(
    time_h: float, doses: tuple[DoseEvent, ...], params: PkParameters
) -> float:
    """Predicted whole-blood concentration at a time, by superposition over all prior doses.

    Args:
        time_h: Time to evaluate, in hours on the same axis as the dose events.
        doses: The patient's dosing history. Order is irrelevant.
        params: Individual PK parameters.

    Returns:
        Predicted concentration in ng/mL. Never negative.

    Raises:
        PkInputError: If time_h is a bool or non-finite.
    """
    _require_finite(time_h, "time_h")

    total_mg_per_l = 0.0
    for dose in doses:
        total_mg_per_l += _single_dose_concentration_mg_per_l(
            dose.delivered_mg, time_h - dose.time_h, params
        )

    # Superposition of non-negative terms cannot go below zero; clamp guards float noise only.
    return max(0.0, total_mg_per_l * MG_PER_L_TO_NG_PER_ML)
