"""Tests for the two recognised multi-sample monitoring measures.

The negative tests are the deliverable here, not the happy path: a suite that only checks a
steady patient scores low would pass against an implementation that always returns zero.
"""

from __future__ import annotations

import math

import pytest

from agent_pk.pk.model import Observation, PkInputError
from agent_pk.pk.variability import (
    HIGH_IPV_THRESHOLD_PERCENT,
    intrapatient_variability_cv_percent,
    MIN_TROUGHS_FOR_IPV,
    time_in_therapeutic_range_percent,
    variability_report,
    variability_report_or_reason,
)

LOW, HIGH = 5.0, 10.0


def _troughs(*pairs: tuple[float, float]) -> tuple[Observation, ...]:
    return tuple(Observation(time_h=t, concentration_ng_per_ml=c) for t, c in pairs)


# ── Intrapatient variability ─────────────────────────────────────────────────


def test_a_perfectly_steady_patient_has_zero_variability() -> None:
    steady = _troughs((0.0, 7.0), (720.0, 7.0), (1440.0, 7.0))
    assert intrapatient_variability_cv_percent(steady) == pytest.approx(0.0)


def test_the_cv_matches_the_published_formula_by_hand() -> None:
    """CV = sigma/mu x 100 with the SAMPLE standard deviation, checked against a hand figure.

    Pinned arithmetically rather than against the implementation, so a change to the estimator
    (population vs sample denominator) fails here instead of silently shifting every patient's
    number against a threshold derived for the published form.
    """
    values = (4.0, 8.0, 6.0)
    observed = _troughs((0.0, 4.0), (24.0, 8.0), (48.0, 6.0))
    mean = sum(values) / 3
    variance = sum((v - mean) ** 2 for v in values) / 2  # n-1
    expected = math.sqrt(variance) / mean * 100.0
    assert intrapatient_variability_cv_percent(observed) == pytest.approx(expected)
    assert expected == pytest.approx(33.33, abs=0.01)


def test_a_swinging_patient_crosses_the_recognised_threshold() -> None:
    """The 30% line must actually separate a steady patient from a swinging one."""
    swinging = _troughs((0.0, 3.0), (720.0, 11.0), (1440.0, 4.0), (2160.0, 10.0))
    steady = _troughs((0.0, 7.2), (720.0, 6.9), (1440.0, 7.1), (2160.0, 7.0))
    assert intrapatient_variability_cv_percent(swinging) >= HIGH_IPV_THRESHOLD_PERCENT
    assert intrapatient_variability_cv_percent(steady) < HIGH_IPV_THRESHOLD_PERCENT


def test_too_few_troughs_is_a_refusal_not_a_number() -> None:
    """Fewer than three samples cannot give a CV comparable against the published threshold.

    Two reasons, both fail-closed. A single sample cannot show variability at all, and 0% would
    read as a perfectly steady patient — the dangerous answer is the reassuring one. And at n=2
    the sample standard deviation exceeds the population form by sqrt(2), so the same patient
    lands either side of the 30% line by choice of estimator: troughs of 5.5 and 9.5 give a
    sample CV of ~37.7% against a population CV of ~26.7%.
    """
    with pytest.raises(PkInputError, match="at least 3"):
        intrapatient_variability_cv_percent(_troughs((0.0, 7.0)))
    with pytest.raises(PkInputError, match="at least 3"):
        intrapatient_variability_cv_percent(_troughs((0.0, 5.5), (24.0, 9.5)))


def test_contradictory_samples_at_one_instant_are_refused() -> None:
    """Two DIFFERENT values at the same time are contradictory data, not a duplicate record.

    Skipping them silently would hide a concentration jump from the interpolation AND make the
    answer depend on sort order among ties. A true duplicate — the identical value recorded
    twice — is harmless and is still accepted.
    """
    with pytest.raises(PkInputError, match="same time"):
        time_in_therapeutic_range_percent(
            _troughs((0.0, 6.0), (100.0, 4.0), (100.0, 9.0), (200.0, 7.0)), LOW, HIGH
        )
    identical = _troughs((0.0, 6.0), (100.0, 7.0), (100.0, 7.0), (200.0, 7.0))
    assert time_in_therapeutic_range_percent(identical, LOW, HIGH) == pytest.approx(
        100.0
    )


# ── Time in therapeutic range ────────────────────────────────────────────────


def test_a_patient_always_in_range_scores_one_hundred() -> None:
    inside = _troughs((0.0, 6.0), (720.0, 8.0), (1440.0, 7.0))
    assert time_in_therapeutic_range_percent(inside, LOW, HIGH) == pytest.approx(100.0)


def test_a_patient_always_outside_scores_zero() -> None:
    below = _troughs((0.0, 2.0), (720.0, 3.0), (1440.0, 2.5))
    assert time_in_therapeutic_range_percent(below, LOW, HIGH) == pytest.approx(0.0)


def test_ttr_measures_time_not_samples() -> None:
    """The whole point of the Rosendaal method, pinned so it cannot regress to sample-counting.

    Two samples, one in range and one far below. Counting SAMPLES would give 50%. Interpolating
    linearly, the level crosses the lower boundary partway through, and only the portion before
    the crossing counts. With 9.0 falling to 1.0 across the segment and a boundary at 5.0, the
    value span is 8.0 and the in-range portion spans 9.0 down to 5.0 — half of it.
    """
    crossing = _troughs((0.0, 9.0), (100.0, 1.0))
    assert time_in_therapeutic_range_percent(crossing, LOW, HIGH) == pytest.approx(50.0)


def test_ttr_weights_by_the_length_of_each_gap() -> None:
    """A long spell out of range must cost more than a short one, which sample-counting misses.

    The first version of this test used a symmetric pair — a dip near the start against a dip
    near the end — and both scored exactly 40%. That is CORRECT behaviour, not a bug: reversing
    which segment is long swaps two equal contributions. The pair simply could not discriminate,
    which is worth recording because a test that cannot fail for the right reason is not a test.
    The pair below differs in how long the patient is out of range in total, which is the
    property actually claimed.
    """
    brief_excursion = _troughs((0.0, 7.0), (10.0, 2.0), (20.0, 7.0), (1000.0, 7.0))
    long_excursion = _troughs((0.0, 7.0), (500.0, 2.0), (1000.0, 7.0))
    assert time_in_therapeutic_range_percent(
        brief_excursion, LOW, HIGH
    ) > time_in_therapeutic_range_percent(long_excursion, LOW, HIGH)


def test_a_segment_that_passes_through_the_range_counts_only_the_crossing() -> None:
    """From above the range to below it: only the middle stretch is in range."""
    # 1.0 rather than 0.0 as the end point: `Observation` requires a strictly positive
    # concentration, so a zero would be refused at construction rather than reaching this
    # function. Worth knowing — a zero level is not a representable measurement here.
    through = _troughs((0.0, 15.0), (100.0, 1.0))
    # Value span 15 -> 1 = 14; the in-range slice is 10 -> 5, i.e. 5 of 14.
    assert time_in_therapeutic_range_percent(through, LOW, HIGH) == pytest.approx(
        100.0 * 5.0 / 14.0
    )


def test_ttr_refuses_a_malformed_range_and_a_zero_span() -> None:
    valid = _troughs((0.0, 6.0), (24.0, 7.0))
    with pytest.raises(PkInputError, match="must exceed"):
        time_in_therapeutic_range_percent(valid, HIGH, LOW)
    with pytest.raises(PkInputError, match="no time elapses|same time"):
        time_in_therapeutic_range_percent(_troughs((5.0, 6.0), (5.0, 6.0)), LOW, HIGH)


def test_ttr_is_order_independent() -> None:
    """Real records arrive unsorted; the answer must not depend on insertion order."""
    forward = _troughs((0.0, 9.0), (100.0, 1.0), (200.0, 8.0))
    shuffled = _troughs((200.0, 8.0), (0.0, 9.0), (100.0, 1.0))
    assert time_in_therapeutic_range_percent(forward, LOW, HIGH) == pytest.approx(
        time_in_therapeutic_range_percent(shuffled, LOW, HIGH)
    )


# ── The combined report ──────────────────────────────────────────────────────


def test_the_report_carries_the_context_needed_to_read_it() -> None:
    """n_samples and span travel with the figures because they decide how much weight to give.

    An IPV over three samples and one over twenty are not equally trustworthy, and a TTR
    interpolated across a six-month gap is a much weaker claim than one across six weeks.
    """
    troughs = _troughs((0.0, 3.0), (720.0, 11.0), (1440.0, 4.0), (2160.0, 10.0))
    report = variability_report(troughs, LOW, HIGH)
    assert report.n_samples == 4
    assert report.span_h == pytest.approx(2160.0)
    assert report.ipv_is_high is (report.ipv_percent >= HIGH_IPV_THRESHOLD_PERCENT)
    assert 0.0 <= report.time_in_range_percent <= 100.0
    # THE TWO MEASURES DISAGREE HERE, AND THAT IS THE POINT RATHER THAN A DEFECT.
    #
    # This patient swings hard (IPV ~58%, far above the 30% line) yet holds a TTR of ~72%,
    # because the swings pass THROUGH the range rather than sitting outside it — most of the
    # elapsed time is spent crossing. An earlier version of this test asserted TTR < 60% on the
    # assumption that a variable patient must also be a poorly-controlled one. That assumption is
    # wrong, and the fact that it is wrong is the reason to report BOTH numbers: variability and
    # range-holding are different clinical questions, and a patient can fail one while passing
    # the other.
    assert report.ipv_is_high
    assert report.time_in_range_percent > 60.0
    assert report.ipv_percent > 50.0


def test_a_duplicate_lab_row_cannot_manufacture_a_third_observation() -> None:
    """IPV must apply the same data-quality rule as TTR, or a repeated row changes the verdict.

    The witness an adversarial review supplied: two troughs plus a duplicate of the first passes
    a naive three-sample count and reports a high CV, while the SAME patient without the repeated
    row is refused at n=2. A duplicated lab record would then manufacture a non-adherence
    suspicion out of nothing.
    """
    with pytest.raises(PkInputError, match="DISTINCT times"):
        intrapatient_variability_cv_percent(
            _troughs((0.0, 5.5), (0.0, 5.5), (100.0, 9.5))
        )
    # ...and genuinely contradictory values at one instant are refused rather than deduplicated.
    with pytest.raises(PkInputError, match="same time"):
        intrapatient_variability_cv_percent(
            _troughs((0.0, 5.5), (0.0, 8.0), (100.0, 9.5), (200.0, 6.0))
        )


# ── The soft form: a reason instead of an exception (T8-2) ───────────────────
#
# A patient early in monitoring genuinely has too few troughs, which is an ordinary state and
# not an error. The soft form exists so a caller building a clinician view can tell that state
# apart from "measured and unremarkable" — but the softening must not swallow a genuine defect,
# and these tests draw that line.


def test_thin_data_returns_a_reason_rather_than_raising() -> None:
    report, reason = variability_report_or_reason(
        _troughs((0.0, 6.0), (720.0, 7.0)), LOW, HIGH
    )
    assert report is None
    assert reason.strip()


def test_the_reason_says_it_is_a_gap_in_the_record_not_a_finding() -> None:
    """The wording carries the safety property, so the wording is asserted.

    "No variability figures" is read as "variability is fine" unless the text refuses that
    reading. This is the same class as the loader's absence-is-not-evidence statement: the
    disclosure has to be IN the value, because the value is what gets displayed.
    """
    _, reason = variability_report_or_reason(_troughs((0.0, 6.0)), LOW, HIGH)
    lowered = reason.lower()
    assert "not a finding about the patient" in lowered
    assert "none should be assumed" in lowered


def test_the_reason_names_the_minimum_it_needs() -> None:
    """A clinician reading it should know what would make the figures available."""
    _, reason = variability_report_or_reason(
        _troughs((0.0, 6.0), (720.0, 7.0)), LOW, HIGH
    )
    assert str(MIN_TROUGHS_FOR_IPV) in reason


def test_duplicate_timestamps_do_not_manufacture_a_third_sample() -> None:
    """The s8 defect, re-asserted at the soft boundary.

    A repeated lab row must not clear the three-sample minimum. If it did, a duplicated record
    would manufacture a variability figure — and with it a non-adherence suspicion — out of a
    database artefact.
    """
    report, reason = variability_report_or_reason(
        _troughs((0.0, 5.5), (0.0, 5.5), (720.0, 9.5)), LOW, HIGH
    )
    assert report is None
    assert reason.strip()


def test_sufficient_data_returns_a_report_and_an_empty_reason() -> None:
    """Exactly one of the two is populated. That is the invariant ClinicianView checks."""
    report, reason = variability_report_or_reason(
        _troughs((0.0, 5.5), (720.0, 9.5), (1440.0, 6.1)), LOW, HIGH
    )
    assert report is not None
    assert reason == ""


def test_the_soft_form_agrees_with_the_hard_form_when_both_can_run() -> None:
    """The softening must not have changed any number."""
    troughs = _troughs((0.0, 5.5), (720.0, 9.5), (1440.0, 6.1))
    soft, _ = variability_report_or_reason(troughs, LOW, HIGH)
    hard = variability_report(troughs, LOW, HIGH)
    assert soft == hard


@pytest.mark.parametrize(
    ("low", "high"),
    [(10.0, 5.0), (5.0, 5.0), (math.nan, 10.0), (5.0, math.inf)],
)
def test_a_malformed_bound_still_raises(low: float, high: float) -> None:
    """A broken care plan must not present as a patient who simply has too few samples.

    This is where the softening stops. Converting a malformed bound into a soft "unavailable"
    would hide a plan defect behind an ordinary-looking data-thinness message, and nobody would
    ever go looking for it.
    """
    troughs = _troughs((0.0, 5.5), (720.0, 9.5), (1440.0, 6.1))
    with pytest.raises(PkInputError):
        variability_report_or_reason(troughs, low, high)


def test_contradictory_troughs_raise_rather_than_reporting_thin_data() -> None:
    """ADOPTED FROM AN ADVERSARIAL REVIEW (s9, Stage A, MEDIUM).

    The witness the seat supplied: three DISTINCT times clear the thin-data pre-check, but two
    different concentrations are recorded at the same instant. The first version caught the
    resulting PkInputError and reported it to a clinician as "not enough samples yet" — telling
    them to wait for data they already have, when the truth is that the record contradicts
    itself. That is the same absent-reads-as-normal failure the pair exists to prevent, moved
    into the reason string.

    The maker's stated justification was that the only reachable cause past the pre-check was a
    zero elapsed span. That was wrong in both directions, and the next test is the other half.
    """
    contradictory = _troughs((0.0, 5.0), (0.0, 6.0), (50.0, 7.0), (100.0, 8.0))
    with pytest.raises(PkInputError, match="two different concentrations"):
        variability_report_or_reason(contradictory, LOW, HIGH)


def test_the_zero_span_case_is_unreachable_past_the_pre_check() -> None:
    """The other half of the same finding, asserted so the reasoning cannot rot.

    A zero elapsed span requires every trough at one instant, which is at most ONE distinct
    time — so it is refused by the distinct-times pre-check as thin data and never reaches the
    computation. The catch that existed to handle it was therefore guarding nothing while
    swallowing defects that mattered.
    """
    same_instant = _troughs((0.0, 5.0), (0.0, 5.0), (0.0, 5.0))
    report, reason = variability_report_or_reason(same_instant, LOW, HIGH)
    assert report is None
    assert "Not enough samples yet" in reason


def test_a_non_positive_concentration_is_refused_before_it_reaches_these_measures() -> (
    None
):
    """Recorded because the maker nearly asserted the wrong thing about it.

    A non-positive mean is a third `PkInputError` inside the IPV computation, and the first
    draft of this test claimed the removed catch would have hidden it. It would not: it is
    UNREACHABLE, because `Observation` refuses a non-positive concentration at construction, so
    no such trough can be built to pass in. That guard is defensive depth, not a live branch.

    The test asserts what is actually true — the refusal happens at the boundary — rather than
    wrapping the same call in `pytest.raises` and passing for a reason it does not name. A test
    that passes for the wrong reason is the failure mode this project keeps producing, and it
    was one line away here.
    """
    with pytest.raises(PkInputError, match="concentration_ng_per_ml must be > 0"):
        Observation(time_h=0.0, concentration_ng_per_ml=0.0)


def test_a_contradiction_is_refused_even_when_samples_are_too_few() -> None:
    """ADOPTED FROM A DECORRELATED SECOND-LINEAGE REVIEW (s9, Stage B, MEDIUM).

    The first fix was fitted to the FIRST reviewer's witness, which had three distinct times and
    so reached the contradiction raise. This witness has TWO, so the thinness pre-check answered
    first and reported "not enough samples yet" for a record that contradicts itself.

    A self-contradicting record is DEFECTIVE at any sample count. The count is not a reason to
    stop looking at the contradiction, so the contradiction is now checked first.
    """
    two_distinct_with_clash = _troughs((0.0, 5.0), (0.0, 6.0), (50.0, 7.0))
    with pytest.raises(PkInputError, match="two different concentrations"):
        variability_report_or_reason(two_distinct_with_clash, LOW, HIGH)


def test_a_contradiction_is_refused_at_the_smallest_possible_input() -> None:
    """One distinct time, two conflicting values. The count could not be lower."""
    with pytest.raises(PkInputError, match="two different concentrations"):
        variability_report_or_reason(_troughs((0.0, 5.0), (0.0, 6.0)), LOW, HIGH)


def test_a_repeated_identical_row_is_still_ordinary_thin_data() -> None:
    """The other side: a duplicate that AGREES is not a contradiction, just not new information."""
    report, reason = variability_report_or_reason(
        _troughs((0.0, 5.5), (0.0, 5.5), (720.0, 9.5)), LOW, HIGH
    )
    assert report is None
    assert "Not enough samples yet" in reason


def test_n_samples_counts_distinct_times_not_rows() -> None:
    """s9, Stage B, LOW — the count and the computation must agree.

    The CV ignores a duplicate timestamp. Counting it in `n_samples` would advertise the figures
    as resting on more observations than they do, and `n_samples` exists precisely so a reader
    can judge how much to trust them.
    """
    report, reason = variability_report_or_reason(
        _troughs((0.0, 5.5), (0.0, 5.5), (720.0, 9.5), (1440.0, 6.1)), LOW, HIGH
    )
    assert report is not None and reason == ""
    assert report.n_samples == 3
