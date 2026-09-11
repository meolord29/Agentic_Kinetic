"""test_channel.py — the two-channel permission boundary, tested as a boundary.

A happy-path suite would pass on a version of this module that leaks. So the tests here are
mostly NEGATIVES and INVARIANTS:

  * the patient view's field set is asserted EXACTLY, so widening it fails the suite;
  * two clinician views that differ ONLY in which way the level is drifting must project to
    IDENTICAL patient views — the direction of travel is an interpretation and may not cross;
  * a recommendation cannot be constructed without the basis criterion 4 requires;
  * a proposal the clinician has not accepted does not reach the patient's phone.

Every patient, dose and level here is synthetic.
"""

from __future__ import annotations

import dataclasses

import pytest

from agent_pk.channel import (
    PATIENT_MESSAGE_BODY,
    PATIENT_VIEW_FIELDS,
    Attribution,
    ChannelBoundaryError,
    ClinicalAction,
    ClinicianView,
    ConcurrentObservation,
    EvidenceNote,
    ParameterEstimate,
    PatientMessage,
    PatientView,
    SampleAppointment,
    general_evaluation_notice,
    to_patient_view,
)
from agent_pk.channel.views import _ACTION_TO_PATIENT_MESSAGE
from agent_pk.pk.fit import Prediction
from agent_pk.pk.model import DoseEvent, Observation, PkInputError
from agent_pk.pk.variability import VariabilityReport, variability_report_or_reason

PLAN_TEXT = "Your team's target range is 5 to 8. Take both doses on an empty stomach."

OWN_DOSES = (
    DoseEvent(time_h=0.0, amount_mg=2.0, status="taken"),
    DoseEvent(time_h=24.0, amount_mg=2.0, status="taken"),
)
OWN_RESULTS = (
    Observation(time_h=24.0, concentration_ng_per_ml=6.4),
    Observation(time_h=48.0, concentration_ng_per_ml=5.9),
)

PARAMETERS = (
    ParameterEstimate(label="CL/F", value=21.0, lower=17.2, upper=25.6, unit="L/h"),
    ParameterEstimate(label="V/F", value=500.0, lower=390.0, upper=641.0, unit="L"),
)
EVIDENCE = (
    EvidenceNote(
        claim="CYP3A5 expressers show roughly 1.64x higher apparent clearance.",
        source_url="https://pubmed.ncbi.nlm.nih.gov/42477302/",
        population_limit="Review of 68 population models; coefficients are illustrative.",
    ),
)
ATTRIBUTIONS = (
    Attribution(
        factor="fluconazole",
        direction="raises",
        magnitude_ng_per_ml=None,
        source="FDA Prograf prescribing information",
    ),
)


_NO_VARIABILITY_REASON = (
    "Not enough samples yet: these measures need at least 3 trough levels drawn at "
    "different times. This is a gap in the record, not a finding about the patient."
)


def _prediction(*, below: bool, above: bool) -> Prediction:
    """Build a Prediction whose interval crosses the requested boundary."""
    if below:
        return Prediction(
            time_h=72.0,
            median_ng_per_ml=5.2,
            lower_ng_per_ml=3.4,
            upper_ng_per_ml=7.1,
            credible_mass=0.90,
            crosses_below=True,
            crosses_above=False,
            probability_below=0.18,
            probability_above=0.0,
            usable_fraction=1.0,
            haematocrit_known=True,
        )
    if above:
        return Prediction(
            time_h=72.0,
            median_ng_per_ml=9.8,
            lower_ng_per_ml=7.9,
            upper_ng_per_ml=13.2,
            credible_mass=0.90,
            crosses_below=False,
            crosses_above=True,
            probability_below=0.0,
            probability_above=0.14,
            usable_fraction=1.0,
            haematocrit_known=True,
        )
    return Prediction(
        time_h=72.0,
        median_ng_per_ml=6.5,
        lower_ng_per_ml=5.4,
        upper_ng_per_ml=7.6,
        credible_mass=0.90,
        crosses_below=False,
        crosses_above=False,
        probability_below=0.01,
        probability_above=0.01,
        usable_fraction=1.0,
        haematocrit_known=True,
    )


def _clinician_view(
    action: ClinicalAction,
    *,
    prediction: Prediction | None = None,
    proposed_sampling: SampleAppointment | None = None,
    variability: VariabilityReport | None = None,
    variability_unavailable_reason: str | None = None,
) -> ClinicianView:
    """Build a well-formed ClinicianView for the action under test.

    The variability pair defaults to the ABSENT-with-a-reason state rather than to a report,
    because that is the state most patients are in early on and the one whose handling this
    module is trying to get right. A caller that wants figures passes them explicitly.
    """
    if variability_unavailable_reason is None:
        variability_unavailable_reason = "" if variability else _NO_VARIABILITY_REASON
    return ClinicianView(
        action=action,
        prediction=prediction or _prediction(below=False, above=False),
        parameters=PARAMETERS,
        attributions=ATTRIBUTIONS,
        evidence=EVIDENCE,
        n_observations=4,
        calibration_note="Profile 34% calibrated on 4 troughs.",
        proposed_sampling=proposed_sampling,
        variability=variability,
        variability_unavailable_reason=variability_unavailable_reason,
    )


def _project(view: ClinicianView) -> PatientView:
    return to_patient_view(
        view,
        plan_text_from_clinician=PLAN_TEXT,
        own_doses=OWN_DOSES,
        own_results=OWN_RESULTS,
    )


# ── The permission boundary itself ───────────────────────────────────────────


def test_patient_view_field_set_is_exactly_the_permitted_set() -> None:
    """Widening the patient channel must be a deliberate act that fails this test first.

    Asserted against the dataclass fields rather than a hand-written list, so a field added to
    PatientView and forgotten in PATIENT_VIEW_FIELDS is caught in either direction.
    """
    actual = {field.name for field in dataclasses.fields(PatientView)}
    assert actual == set(PATIENT_VIEW_FIELDS)


def test_no_patient_view_field_can_hold_a_prediction() -> None:
    """A prediction has no field to live in. The type is the boundary, not the discipline."""
    annotations = {f.name: f.type for f in dataclasses.fields(PatientView)}
    for name, annotation in annotations.items():
        assert "Prediction" not in str(annotation), (
            f"PatientView.{name} is annotated {annotation!r} — a predicted concentration "
            f"must not have anywhere to sit in the patient channel"
        )


def test_every_clinical_action_has_a_patient_mapping() -> None:
    """The import-time completeness check, asserted so a reader can see what it guarantees."""
    assert set(_ACTION_TO_PATIENT_MESSAGE) == set(ClinicalAction)


def test_every_patient_message_has_a_body() -> None:
    assert set(PATIENT_MESSAGE_BODY) == set(PatientMessage)
    for message, body in PATIENT_MESSAGE_BODY.items():
        assert body.strip(), f"{message} has an empty body"


# ── Direction of travel must not cross ───────────────────────────────────────


def test_drifting_low_and_drifting_high_produce_identical_patient_views() -> None:
    """The single most important property in this module.

    A patient who can tell 'your level is falling' from 'your level is rising' has been given
    an interpretation, which is exactly what the patient channel may not do. The two views must
    be indistinguishable.
    """
    low = _project(
        _clinician_view(
            ClinicalAction.FLAG_FOR_REVIEW,
            prediction=_prediction(below=True, above=False),
        )
    )
    high = _project(
        _clinician_view(
            ClinicalAction.FLAG_FOR_REVIEW,
            prediction=_prediction(below=False, above=True),
        )
    )
    assert low == high
    assert low.body == high.body


def test_dose_reduction_and_dose_increase_produce_identical_patient_views() -> None:
    """Same property, one layer up: the direction of a proposed dose change may not leak."""
    down = _project(_clinician_view(ClinicalAction.CONSIDER_DOSE_REDUCTION))
    up = _project(_clinician_view(ClinicalAction.CONSIDER_DOSE_INCREASE))
    assert down == up


def test_urgency_does_not_cross_to_the_patient() -> None:
    """Urgency is both an interpretation and a time-critical output. It stays clinician-side."""
    routine = _project(_clinician_view(ClinicalAction.FLAG_FOR_REVIEW))
    urgent = _project(_clinician_view(ClinicalAction.URGENT_REVIEW))
    assert routine == urgent
    assert "urgent" not in urgent.body.lower()


def test_no_patient_message_body_names_a_number_or_a_range() -> None:
    """No body may carry a digit. A threshold in patient copy is a clinical threshold."""
    for message, body in PATIENT_MESSAGE_BODY.items():
        assert not any(char.isdigit() for char in body), (
            f"{message} body contains a digit: {body!r}"
        )


# ── The recommendation cannot be separated from its basis ────────────────────


def test_clinician_view_refuses_a_recommendation_without_fitted_parameters() -> None:
    with pytest.raises(ChannelBoundaryError, match="fitted parameters"):
        ClinicianView(
            action=ClinicalAction.FLAG_FOR_REVIEW,
            prediction=_prediction(below=True, above=False),
            parameters=(),
            attributions=ATTRIBUTIONS,
            evidence=EVIDENCE,
            n_observations=4,
            calibration_note="",
        )


def test_clinician_view_refuses_a_recommendation_without_citations() -> None:
    with pytest.raises(ChannelBoundaryError, match="citations"):
        ClinicianView(
            action=ClinicalAction.FLAG_FOR_REVIEW,
            prediction=_prediction(below=True, above=False),
            parameters=PARAMETERS,
            attributions=ATTRIBUTIONS,
            evidence=(),
            n_observations=4,
            calibration_note="",
        )


# ── Scheduling: a proposal is not a booking ──────────────────────────────────


def test_a_proposal_the_clinician_has_not_accepted_does_not_reach_the_patient() -> None:
    """The sampling offer is the clinician's decision. Until they take it, nothing is booked."""
    appointment = SampleAppointment(
        start_time_h=72.0,
        offsets_post_dose_h=(0.0, 1.0, 3.0, 6.0),
        fasted_required=True,
    )
    view = _clinician_view(
        ClinicalAction.FLAG_FOR_REVIEW, proposed_sampling=appointment
    )
    assert _project(view).next_sample is None


def test_an_accepted_sampling_action_carries_the_appointment_across() -> None:
    appointment = SampleAppointment(
        start_time_h=72.0,
        offsets_post_dose_h=(0.0, 1.0, 3.0, 6.0),
        fasted_required=True,
    )
    view = _clinician_view(
        ClinicalAction.SCHEDULE_ADDITIONAL_PK_SAMPLE, proposed_sampling=appointment
    )
    projected = _project(view)
    assert projected.next_sample == appointment
    assert projected.message is PatientMessage.SAMPLE_SCHEDULED


def test_scheduling_action_without_an_appointment_raises() -> None:
    with pytest.raises(PkInputError, match="requires a proposed_sampling"):
        _clinician_view(ClinicalAction.SCHEDULE_ADDITIONAL_PK_SAMPLE)


# ── Value validation ─────────────────────────────────────────────────────────


def test_patient_view_refuses_a_free_text_message() -> None:
    """A str where a PatientMessage belongs is how an interpolated prediction gets in."""
    with pytest.raises(ChannelBoundaryError, match="PatientMessage"):
        PatientView(
            message="your level is 3.9 and falling",  # type: ignore[arg-type]
            plan_text_from_clinician=PLAN_TEXT,
            own_doses=OWN_DOSES,
            own_results=OWN_RESULTS,
        )


def test_parameter_estimate_rejects_a_value_outside_its_own_interval() -> None:
    with pytest.raises(PkInputError, match="must lie within"):
        ParameterEstimate(label="CL/F", value=30.0, lower=17.2, upper=25.6, unit="L/h")


def test_attribution_keeps_an_absent_magnitude_absent() -> None:
    """An unknown size is not a zero size. Coercing one to the other invents a measurement."""
    attribution = Attribution(
        factor="diltiazem",
        direction="raises",
        magnitude_ng_per_ml=None,
        source="literature",
    )
    assert attribution.magnitude_ng_per_ml is None


def test_attribution_rejects_an_unknown_direction() -> None:
    with pytest.raises(PkInputError, match="direction must be"):
        Attribution(
            factor="fluconazole",
            direction="probably up",
            magnitude_ng_per_ml=None,
            source="label",
        )


@pytest.mark.parametrize(
    ("offsets", "match"),
    [
        ((), "must not be empty"),
        ((0.0, 1.0, 1.0), "must not repeat"),
        ((6.0, 1.0, 0.0), "ascending order"),
        ((0.0, -1.0, 3.0), "offsets_post_dose_h"),
    ],
)
def test_sample_appointment_rejects_a_malformed_schedule(
    offsets: tuple[float, ...], match: str
) -> None:
    with pytest.raises(PkInputError, match=match):
        SampleAppointment(
            start_time_h=72.0, offsets_post_dose_h=offsets, fasted_required=True
        )


def test_sample_appointment_rejects_a_bool_masquerading_as_a_time() -> None:
    """bool subclasses int, so True would otherwise pass every numeric check as 1.0."""
    with pytest.raises(PkInputError):
        SampleAppointment(
            start_time_h=True,  # type: ignore[arg-type]
            offsets_post_dose_h=(0.0, 1.0),
            fasted_required=True,
        )


# ── The patient-initiated path ───────────────────────────────────────────────


def test_general_evaluation_notice_names_no_condition_and_books_nothing() -> None:
    notice = general_evaluation_notice(
        plan_text_from_clinician=PLAN_TEXT,
        own_doses=OWN_DOSES,
        own_results=OWN_RESULTS,
    )
    assert notice.message is PatientMessage.EVALUATION_MAY_BE_HELPFUL
    assert notice.next_sample is None
    body = notice.body.lower()
    for forbidden in ("tacrolimus", "rejection", "transplant", "kidney", "level"):
        assert forbidden not in body, f"the general notice must not say {forbidden!r}"


def test_the_patient_keeps_their_own_data_and_their_clinicians_own_words() -> None:
    """(o)(1)(D) permits exactly this: their results, and their clinician's findings on them."""
    projected = _project(_clinician_view(ClinicalAction.NO_ACTION))
    assert projected.own_doses == OWN_DOSES
    assert projected.own_results == OWN_RESULTS
    assert projected.plan_text_from_clinician == PLAN_TEXT
    assert projected.message is PatientMessage.NOTHING_TO_DO


# ── Concurrent observations: the clinician decides what else is tracked ──────


def test_the_agent_cannot_author_a_concurrent_observation() -> None:
    """The whole safety property of this feature is authorship.

    A clinician telling their own patient to weigh themselves is the clinician's own finding
    about their own patient, which (o)(1)(D) permits to be displayed verbatim. The identical
    sentence generated by the software is the software telling a patient what to do about their
    condition. Same words, different act — so authorship is a checked field, not a convention.
    """
    with pytest.raises(ChannelBoundaryError, match="not clinician-authored"):
        ConcurrentObservation(
            label="Morning weight",
            instruction="Weigh yourself before breakfast.",
            authored_by_clinician=False,
        )


def test_a_clinician_authored_observation_is_accepted() -> None:
    obs = ConcurrentObservation(
        label="Morning weight",
        instruction="Weigh yourself fasting, before coffee, and log it.",
        authored_by_clinician=True,
    )
    assert obs.label == "Morning weight"


def test_concurrent_observations_reach_the_patient_with_the_booked_appointment() -> (
    None
):
    """They are logistics, so they are safe in the patient channel — but only once booked."""
    obs = ConcurrentObservation(
        label="Urine output",
        instruction="Count how many times you pass urine tonight.",
        authored_by_clinician=True,
    )
    appointment = SampleAppointment(
        start_time_h=72.0,
        offsets_post_dose_h=(0.0, 1.0, 3.0, 6.0),
        fasted_required=True,
        concurrent_observations=(obs,),
    )
    view = _clinician_view(
        ClinicalAction.SCHEDULE_ADDITIONAL_PK_SAMPLE, proposed_sampling=appointment
    )
    projected = _project(view)
    assert projected.next_sample is not None
    assert projected.next_sample.concurrent_observations == (obs,)


def test_burden_counts_the_whole_ask_not_only_the_needles() -> None:
    """A design that counts only draws understates what the patient is being asked for."""
    appointment = SampleAppointment(
        start_time_h=72.0,
        offsets_post_dose_h=(0.0, 1.0, 3.0, 6.0),
        fasted_required=True,
        concurrent_observations=(
            ConcurrentObservation("Morning weight", "Weigh fasting.", True),
            ConcurrentObservation("Urine output", "Count tonight.", True),
        ),
    )
    assert appointment.total_patient_burden == 5  # 3 extra draws + 2 things to record


def test_an_appointment_asks_for_nothing_extra_by_default() -> None:
    appointment = SampleAppointment(
        start_time_h=72.0,
        offsets_post_dose_h=(0.0, 1.0, 3.0, 6.0),
        fasted_required=True,
    )
    assert appointment.concurrent_observations == ()
    assert appointment.total_patient_burden == 3


def test_duplicate_concurrent_labels_are_refused() -> None:
    with pytest.raises(PkInputError, match="must not repeat a label"):
        SampleAppointment(
            start_time_h=72.0,
            offsets_post_dose_h=(0.0, 1.0),
            fasted_required=True,
            concurrent_observations=(
                ConcurrentObservation("Weight", "Weigh fasting.", True),
                ConcurrentObservation("Weight", "Weigh again.", True),
            ),
        )


# ── Variability reaches the clinician, and never the patient (T8-2) ──────────


def _troughs(*pairs: tuple[float, float]) -> tuple[Observation, ...]:
    """Build troughs from (time_h, concentration) pairs."""
    return tuple(Observation(time_h=t, concentration_ng_per_ml=c) for t, c in pairs)


def test_absent_variability_without_a_reason_is_refused() -> None:
    """The whole point of the pair.

    A bare `variability=None` on a screen is indistinguishable from "measured, and fine". That
    exact ambiguity — an unmeasured value presenting as a reassuring one — is the defect a
    review caught twice on the haematocrit path, once on the prior and again one layer down at
    the fit boundary. Here it is made unrepresentable rather than guarded against.
    """
    with pytest.raises(ChannelBoundaryError, match="no reason was given"):
        _clinician_view(
            ClinicalAction.FLAG_FOR_REVIEW, variability_unavailable_reason=""
        )


def test_a_whitespace_reason_does_not_satisfy_the_requirement() -> None:
    """Otherwise the check is satisfiable by a space bar."""
    with pytest.raises(ChannelBoundaryError, match="no reason was given"):
        _clinician_view(
            ClinicalAction.FLAG_FOR_REVIEW, variability_unavailable_reason="   "
        )


def test_present_variability_with_a_reason_is_refused() -> None:
    """Both fields populated means the view holds two answers to one question."""
    report, reason = variability_report_or_reason(
        _troughs((0.0, 5.5), (720.0, 9.5), (1440.0, 6.1)), 5.0, 10.0
    )
    assert report is not None and reason == ""
    with pytest.raises(PkInputError, match="must be empty when variability is present"):
        _clinician_view(
            ClinicalAction.FLAG_FOR_REVIEW,
            variability=report,
            variability_unavailable_reason="some leftover reason",
        )


def test_a_clinician_view_carries_the_figures_when_they_exist() -> None:
    """IPV and TTR were built in s8 and called by nothing. This is the call."""
    report, reason = variability_report_or_reason(
        _troughs((0.0, 5.5), (720.0, 9.5), (1440.0, 6.1)), 5.0, 10.0
    )
    view = _clinician_view(ClinicalAction.FLAG_FOR_REVIEW, variability=report)
    assert view.variability is not None
    assert view.variability.n_samples == 3
    assert 0.0 <= view.variability.time_in_range_percent <= 100.0
    assert view.variability.ipv_percent > 0.0
    assert view.variability_unavailable_reason == ""


def test_variability_does_not_reach_the_patient_channel() -> None:
    """IPV is an adherence signal, and a patient-facing one would be an accusation.

    "Your variability is high" tells a patient the software has inferred something about
    whether they are taking their medicine. That is an interpretation under (o)(1)(D) and it is
    also the single most damaging thing this product could say wrongly, because the measure has
    a 30% threshold that is a convention rather than a derivation.
    """
    report, _ = variability_report_or_reason(
        _troughs((0.0, 2.0), (720.0, 14.0), (1440.0, 3.0)), 5.0, 10.0
    )
    assert report is not None and report.ipv_is_high, (
        "the witness must actually be a high-IPV patient or this test proves nothing"
    )
    patient = _project(
        _clinician_view(ClinicalAction.FLAG_FOR_REVIEW, variability=report)
    )
    field_names = {f.name for f in dataclasses.fields(patient)}
    assert "variability" not in field_names
    assert not any("ipv" in name.lower() for name in field_names)
    assert not any("variab" in name.lower() for name in field_names)


def test_high_and_low_variability_produce_identical_patient_views() -> None:
    """The strongest form of the previous test: the patient view cannot even DIFFER.

    A field-set assertion catches a new field. It does not catch variability leaking through an
    existing field — a different message, or different plan text. Projecting two patients who
    differ ONLY in variability and requiring the results to be equal catches both.
    """
    steady, _ = variability_report_or_reason(
        _troughs((0.0, 6.0), (720.0, 6.2), (1440.0, 5.9)), 5.0, 10.0
    )
    erratic, _ = variability_report_or_reason(
        _troughs((0.0, 2.0), (720.0, 14.0), (1440.0, 3.0)), 5.0, 10.0
    )
    assert steady is not None and erratic is not None
    assert steady.ipv_is_high != erratic.ipv_is_high, "the witnesses must differ"

    a = _project(_clinician_view(ClinicalAction.FLAG_FOR_REVIEW, variability=steady))
    b = _project(_clinician_view(ClinicalAction.FLAG_FOR_REVIEW, variability=erratic))
    assert a == b
