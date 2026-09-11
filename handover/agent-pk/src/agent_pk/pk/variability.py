"""variability.py — the two recognised multi-sample tacrolimus monitoring measures.

**Why this module exists, and why it is not a single trough.** Agent PK's forecast answers a
question about ONE future concentration. That is useful, but it is not how transplant medicine
actually judges whether a patient's immunosuppression is being held steadily — because a single
level moves for a wide range of reasons (a late dose, a meal, an infection, an assay's own error)
and a one-off reading cannot distinguish those from a patient who is genuinely drifting.

The field's answer is to look ACROSS samples, and it has two established measures for it:

1. **Intrapatient variability (IPV)** — how much a patient's own trough levels scatter around
   their own mean. High IPV is associated with de novo donor-specific antibodies, rejection and
   graft loss, and it is one of the few available signals for non-adherence, which asking the
   patient does not reliably reveal.
2. **Time in therapeutic range (TTR)** — what FRACTION OF TIME, not what fraction of samples, the
   patient's level sat inside the plan's range.

Both are adopted here as the recognised diagnostics rather than invented ones, with their
published thresholds and the limits of those thresholds recorded beside them.

**Nothing in this module recommends a dose or an action.** It reports two numbers a clinician
already knows how to read.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from agent_pk.pk.model import Observation, PkInputError, _require_finite

# ── Intrapatient variability ─────────────────────────────────────────────────

IPV_FORMULA = (
    "CV = (standard deviation / mean) x 100%, over a patient's own trough levels"
)
"""The coefficient-of-variation form, which is the one the transplant literature uses.

Stated explicitly because IPV is also reported in the literature as mean absolute deviation and
occasionally as a raw standard deviation, and the three are not interchangeable. A CV computed
here must not be compared against a threshold derived for another form."""

HIGH_IPV_THRESHOLD_PERCENT = 30.0
"""At or above this CV, IPV is conventionally called HIGH.

Source for the formula and the threshold as used in practice: Gavcovich TB, Sigurjonsdottir VK,
DeFreitas MJ, et al. "Intrapatient tacrolimus variability is associated with medical nonadherence
among pediatric kidney transplant recipients." Front Transplant 2025;4:1572928,
doi:10.3389/frtra.2025.1572928, which gives "CV = sigma/mu x 100%" and records that "a highly
variable drug level has been defined in many studies as >=30%", with "Tac IPV exceeding 30%
should prompt heightened clinical suspicion for nonadherence". In that cohort non-adherent
patients had a median IPV of 31% against 20% in adherent patients (p<0.001), and IPV predicted
adherence with an AUC of 0.772.

**AN HONEST NOTE ON THE THRESHOLD'S PROVENANCE, because it matters for how hard to lean on it.**
30% is a CONVENTION established across many studies rather than a value traced to one primary
derivation — the source above explicitly presents it that way rather than citing a single paper
for it. It is also cohort-dependent: the same source reports much lower cut-points (17-20%)
reaching 90%+ sensitivity for non-adherence, so 30% is a specific rather than a sensitive
threshold. Treat it as the recognised line at which to LOOK, not as a diagnosis. The
comprehensive review of the area is Gonzales HM, et al., Am J Transplant 2020,
doi:10.1111/ajt.16002."""


MIN_TROUGHS_FOR_IPV = 3
"""Fewest troughs from which a CV may be compared against the 30% convention.

TWO IS NOT ENOUGH, and the reason is arithmetic rather than cautious. This function uses the
SAMPLE standard deviation (n-1 denominator), which at n=2 is larger than the population form by a
factor of sqrt(2) — about 41%. Concretely: troughs of 5.5 and 9.5 ng/mL give a sample CV of ~37.7%
and a population CV of ~26.7%, so the same patient lands on opposite sides of the 30% line purely
by choice of estimator. Since the published convention is not traceable to one derivation, it
cannot be assumed to use the same form, and a two-sample comparison against it would manufacture
non-adherence suspicion out of a denominator.

Raised by an adversarial review with that witness. Erring toward refusal is the safe direction
here: the cost is an unavailable number, and the alternative is a confident wrong one about a
patient's adherence."""


@dataclass(frozen=True, slots=True)
class VariabilityReport:
    """A patient's own variability and range-holding, over the samples available.

    Attributes:
        ipv_percent: Coefficient of variation of the trough levels, as a percentage.
        ipv_is_high: Whether it reaches the conventional 30% line.
        time_in_range_percent: Fraction of TIME inside the plan's range, as a percentage,
            by linear interpolation between samples.
        n_samples: How many troughs at DISTINCT times the figures rest on. A repeated
            timestamp is not another observation, and is not counted as one.
        span_h: Hours between the first and last sample.
    """

    ipv_percent: float
    ipv_is_high: bool
    time_in_range_percent: float
    n_samples: int
    span_h: float


def intrapatient_variability_cv_percent(troughs: tuple[Observation, ...]) -> float:
    """The patient's own coefficient of variation across their trough levels, as a percentage.

    Uses the SAMPLE standard deviation (n-1 denominator), which is the estimator appropriate to a
    handful of observations standing in for a patient's ongoing behaviour rather than to a
    complete population.

    Args:
        troughs: The patient's measured trough concentrations. At least
            `MIN_TROUGHS_FOR_IPV` at DISTINCT times are required.

    Returns:
        CV as a percentage. Compare against `HIGH_IPV_THRESHOLD_PERCENT`.

    Raises:
        PkInputError: If fewer than `MIN_TROUGHS_FOR_IPV` troughs at DISTINCT times are
            supplied, if two different concentrations sit at one instant, or if the mean is
            not positive. A
            refusal rather than a zero, because a CV of 0 would read as a perfectly steady
            patient — the opposite of "we cannot tell".
    """
    if len(troughs) < MIN_TROUGHS_FOR_IPV:
        raise PkInputError(
            f"intrapatient variability needs at least {MIN_TROUGHS_FOR_IPV} troughs, got "
            f"{len(troughs)} — refusing rather than returning a number, because a CV of 0 would "
            "read as a perfectly steady patient and a two-sample CV is not comparable against "
            "the published threshold (see MIN_TROUGHS_FOR_IPV)"
        )
    # SAME DATA-QUALITY RULE AS TTR, because a duplicate lab row must not change the answer.
    # An adversarial review found the two measures disagreeing here: TTR ignores a repeated
    # timestamp while IPV counted it, so `(t=0, 5.5), (t=0, 5.5), (t=100, 9.5)` passed the
    # three-sample minimum and reported a high CV, while the SAME patient without the duplicate
    # row was refused at n=2. A duplicated record would have manufactured a non-adherence
    # suspicion out of a repeated row.
    by_time: dict[float, float] = {}
    for obs in troughs:
        existing = by_time.get(obs.time_h)
        if existing is not None and existing != obs.concentration_ng_per_ml:
            raise PkInputError(
                f"two different concentrations recorded at the same time (t={obs.time_h!r}: "
                f"{existing!r} and {obs.concentration_ng_per_ml!r}) — contradictory data, "
                "refused rather than averaged or silently deduplicated"
            )
        by_time[obs.time_h] = obs.concentration_ng_per_ml
    if len(by_time) < MIN_TROUGHS_FOR_IPV:
        raise PkInputError(
            f"intrapatient variability needs at least {MIN_TROUGHS_FOR_IPV} troughs at DISTINCT "
            f"times, got {len(by_time)} — a repeated lab row is not another observation"
        )
    values = list(by_time.values())
    mean = sum(values) / len(values)
    if mean <= 0.0 or not math.isfinite(mean):
        raise PkInputError(f"mean trough must be positive and finite, got {mean!r}")
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance) / mean * 100.0


# ── Time in therapeutic range ────────────────────────────────────────────────

TTR_METHOD = (
    "Rosendaal linear interpolation: the concentration is assumed to move linearly between "
    "consecutive measurements, and TTR is the fraction of elapsed TIME the interpolated curve "
    "spends inside the range — not the fraction of samples that happen to be inside it."
)
"""Why the distinction is load-bearing rather than pedantic.

Counting SAMPLES treats a patient measured twice a month and one measured twice a year as
equivalent, and it ignores how long a patient sat outside the range between two readings. The
Rosendaal method was developed for anticoagulation monitoring and is the method the tacrolimus
TTR literature uses. It is an ASSUMPTION about what happened between samples, not an observation,
and it is a poorer assumption the further apart the samples are — which is why `VariabilityReport`
carries `span_h` and `n_samples` beside the figure."""

TTR_CONCERN_THRESHOLDS_PERCENT = (60.0, 75.0, 78.0)
"""Published cut-points below which TTR has been associated with worse outcomes.

THREE VALUES, NOT ONE, and that is the honest state of the evidence rather than indecision.
Different cohorts and different therapeutic ranges have produced different optimal cut-points:
TTR below 60% and below 75% have been associated with de novo donor-specific antibodies and acute
rejection in the first year and with graft loss by five years; a separate analysis identified an
optimal cut-point of 78%, below which acute rejection risk rose independently. A dose-response is
also reported — roughly a 28% lower risk of acute rejection for every 10 percentage points of
additional TTR — which is a more useful way to read the number than any single line.

The key IPV-and-TTR paper for de novo DSA is Transplantation 2019,
doi:10.1097/TP.0000000000002913. **These cut-points are cohort- and range-specific: a TTR is only
comparable against a threshold derived for the SAME therapeutic range.** This project's range is
5-10 ng/mL, which matches the range used in the first-year analyses above."""


def time_in_therapeutic_range_percent(
    troughs: tuple[Observation, ...],
    lower_bound_ng_per_ml: float,
    upper_bound_ng_per_ml: float,
) -> float:
    """Fraction of elapsed TIME inside the range, by Rosendaal linear interpolation.

    Args:
        troughs: Measured troughs with their times. At least two are required, and they may be
            supplied in any order.
        lower_bound_ng_per_ml: The plan's lower boundary.
        upper_bound_ng_per_ml: The plan's upper boundary.

    Returns:
        Percentage of the observed span spent inside the range, in [0, 100].

    Raises:
        PkInputError: If fewer than two troughs are supplied, the bounds are malformed, or every
            sample falls at the same instant so no time elapses.
    """
    _require_finite(lower_bound_ng_per_ml, "lower_bound_ng_per_ml")
    _require_finite(upper_bound_ng_per_ml, "upper_bound_ng_per_ml")
    if upper_bound_ng_per_ml <= lower_bound_ng_per_ml:
        raise PkInputError("upper_bound_ng_per_ml must exceed lower_bound_ng_per_ml")
    if len(troughs) < 2:
        raise PkInputError(
            f"time in therapeutic range needs at least 2 troughs, got {len(troughs)}"
        )

    ordered = sorted(troughs, key=lambda obs: obs.time_h)
    total_h = ordered[-1].time_h - ordered[0].time_h
    if total_h <= 0.0:
        raise PkInputError(
            "all troughs fall at the same time, so no time elapses and no fraction of it can "
            "be in range"
        )

    in_range_h = 0.0
    for start, end in zip(ordered, ordered[1:], strict=False):
        segment_h = end.time_h - start.time_h
        if segment_h <= 0.0:
            # Two samples at the SAME instant. A true duplicate record (identical value) is
            # harmless and contributes no time. Two DIFFERENT values at one instant are not:
            # they are contradictory data, the concentration jump between them is invisible to
            # the interpolation, and which pair forms the zero-length segment depends on sort
            # order among ties — so the answer would depend on input ordering. Refused rather
            # than skipped, because a silently-skipped record is the fail-open pattern this
            # module is otherwise careful about.
            if start.concentration_ng_per_ml != end.concentration_ng_per_ml:
                raise PkInputError(
                    f"two different concentrations recorded at the same time "
                    f"(t={start.time_h!r}: {start.concentration_ng_per_ml!r} and "
                    f"{end.concentration_ng_per_ml!r}) — contradictory data, refused rather "
                    "than silently skipped"
                )
            continue
        in_range_h += segment_h * _fraction_of_segment_in_range(
            start.concentration_ng_per_ml,
            end.concentration_ng_per_ml,
            lower_bound_ng_per_ml,
            upper_bound_ng_per_ml,
        )
    return in_range_h / total_h * 100.0


def _fraction_of_segment_in_range(
    start_value: float, end_value: float, lower: float, upper: float
) -> float:
    """Fraction of one interpolated segment that lies within [lower, upper].

    The concentration is taken to move linearly from `start_value` to `end_value`. Because that
    path is monotonic, the in-range portion is a single contiguous stretch and can be found by
    clipping the value interval to the range and converting back to a fraction of the segment.

    Returns:
        A fraction in [0, 1].
    """
    if start_value == end_value:
        return 1.0 if lower <= start_value <= upper else 0.0

    low_value, high_value = sorted((start_value, end_value))
    overlap = min(high_value, upper) - max(low_value, lower)
    if overlap <= 0.0:
        return 0.0
    # Linear in time, so a fraction of the VALUE span is the same fraction of the TIME span.
    return overlap / (high_value - low_value)


def variability_report(
    troughs: tuple[Observation, ...],
    lower_bound_ng_per_ml: float,
    upper_bound_ng_per_ml: float,
) -> VariabilityReport:
    """Both recognised measures together, with the context needed to read them.

    Args:
        troughs: The patient's measured troughs. At least `MIN_TROUGHS_FOR_IPV` at
            distinct times for the IPV half; at least two for the TTR half.
        lower_bound_ng_per_ml: The plan's lower boundary.
        upper_bound_ng_per_ml: The plan's upper boundary.

    Returns:
        A VariabilityReport. `n_samples` and `span_h` travel with the figures deliberately: an
        IPV over three samples and one over twenty are not equally trustworthy, and a TTR
        interpolated across a six-month gap is a much weaker claim than one across six weeks.

    Raises:
        PkInputError: Propagated from either measure when the inputs cannot support it.
    """
    ordered = sorted(troughs, key=lambda obs: obs.time_h)
    ipv = intrapatient_variability_cv_percent(troughs)
    return VariabilityReport(
        ipv_percent=ipv,
        ipv_is_high=ipv >= HIGH_IPV_THRESHOLD_PERCENT,
        time_in_range_percent=time_in_therapeutic_range_percent(
            troughs, lower_bound_ng_per_ml, upper_bound_ng_per_ml
        ),
        # DISTINCT times, not raw rows (s9, Stage B, LOW). The CV ignores a duplicate
        # timestamp, so counting it here would advertise the figures as resting on more
        # observations than they do — the count and the computation must agree.
        n_samples=len({obs.time_h for obs in troughs}),
        span_h=ordered[-1].time_h - ordered[0].time_h,
    )


def variability_report_or_reason(
    troughs: tuple[Observation, ...],
    lower_bound_ng_per_ml: float,
    upper_bound_ng_per_ml: float,
) -> tuple[VariabilityReport | None, str]:
    """`variability_report`, but returning a stated reason instead of raising on thin data.

    A patient early in monitoring genuinely does not have enough troughs for these measures, and
    that is an ordinary state rather than an error. The caller building a clinician view needs
    to distinguish it from "measured and unremarkable", so this returns the reason as a value
    rather than as an exception a caller may forget to catch — and the reason is written to be
    shown to a clinician, not logged.

    Only the insufficiency conditions are converted. A malformed BOUND is a plan defect rather
    than a data-thinness one, so it still raises: turning it into a soft "unavailable" would let
    a broken care plan present as a patient who simply has too few samples.

    Args:
        troughs: The patient's measured troughs.
        lower_bound_ng_per_ml: The plan's lower boundary.
        upper_bound_ng_per_ml: The plan's upper boundary.

    Returns:
        `(report, "")` when both measures could be computed, or `(None, reason)` when they could
        not. Exactly one of the two is populated, which is the invariant `ClinicianView` checks.

    Raises:
        PkInputError: If the bounds are malformed, or the troughs are DEFECTIVE rather
            than merely few — contradictory concentrations at one instant, or a
            non-positive mean. Never for thin data, which is what the returned reason is
            for. The distinction is the point: too few samples is an ordinary state, a
            self-contradicting record is not, and reporting the second as the first tells
            a clinician to wait for data they already have.
    """
    _require_finite(lower_bound_ng_per_ml, "lower_bound_ng_per_ml")
    _require_finite(upper_bound_ng_per_ml, "upper_bound_ng_per_ml")
    if upper_bound_ng_per_ml <= lower_bound_ng_per_ml:
        raise PkInputError("upper_bound_ng_per_ml must exceed lower_bound_ng_per_ml")

    # CONTRADICTION IS CHECKED BEFORE THINNESS, AND THE ORDER IS THE WHOLE FIX.
    #
    # ADOPTED FROM A DECORRELATED SECOND-LINEAGE REVIEW (s9, Stage B, MEDIUM), which caught
    # that the first fix was fitted to the FIRST reviewer's witness rather than to the property
    # both the spec and this function's own docstring state. That witness had three distinct
    # times, so it reached the contradiction raise inside the IPV computation. This one has two:
    #
    #     (t=0, 5.0), (t=0, 6.0), (t=50, 7.0)
    #
    # Two different concentrations at t=0 — a self-contradicting record — but only two distinct
    # times, so the thinness pre-check returned "not enough samples yet … this patient has 2"
    # and the contradiction was never reached. In the reviewer's words, adding a later sample
    # does not repair the clash at t=0, it only delays the raise.
    #
    # That is the same defect-moves-one-layer pattern this project produced on the haematocrit
    # path in s8: fix it where the reviewer's example hits, and it survives everywhere else.
    # A record that contradicts itself is DEFECTIVE at any sample count, so it must be refused
    # before the count is ever consulted.
    by_time: dict[float, float] = {}
    for obs in troughs:
        existing = by_time.get(obs.time_h)
        if existing is not None and existing != obs.concentration_ng_per_ml:
            raise PkInputError(
                f"two different concentrations recorded at the same time (t={obs.time_h!r}: "
                f"{existing!r} and {obs.concentration_ng_per_ml!r}) — contradictory data, "
                "refused rather than averaged or silently deduplicated"
            )
        by_time[obs.time_h] = obs.concentration_ng_per_ml

    distinct_times = set(by_time)
    if len(distinct_times) < MIN_TROUGHS_FOR_IPV:
        return (
            None,
            f"Not enough samples yet: these measures need at least {MIN_TROUGHS_FOR_IPV} "
            f"trough levels drawn at different times, and this patient has "
            f"{len(distinct_times)}. This is a gap in the record, not a finding about the "
            f"patient — no variability has been measured, and none should be assumed.",
        )
    # NO try/except HERE, DELIBERATELY — and the first draft of this function had one.
    #
    # An adversarial review (s9, Stage A, MEDIUM) found that a broad `except PkInputError`
    # around this call converts DATA CONTRADICTIONS into a data-thinness message. Witness:
    # troughs (t=0, 5.0), (t=0, 6.0), (t=50, 7.0), (t=100, 8.0) clear the distinct-times
    # pre-check above with three distinct times, then raise inside the IPV computation because
    # two DIFFERENT concentrations are recorded at the same instant. Caught, that surfaces to a
    # clinician as "not enough samples yet" — when the truth is that the record contradicts
    # itself. That is the same absent-reads-as-normal failure this pair exists to prevent,
    # relocated into the reason string.
    #
    # The maker's justification for the catch was that the only remaining reachable cause was a
    # zero elapsed span. That was wrong in BOTH directions: a zero span is UNREACHABLE past a
    # three-distinct-times pre-check, and the contradiction and non-positive-mean raises it did
    # not consider are both reachable. Every PkInputError that survives the pre-checks above is
    # therefore a genuine data defect, and every one of them must reach the caller as an
    # exception rather than as a reassuring sentence about sample counts.
    return variability_report(troughs, lower_bound_ng_per_ml, upper_bound_ng_per_ml), ""
