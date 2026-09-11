"""views.py — the two-channel permission boundary, enforced by types rather than by care.

Agent PK is one product with two software functions carrying different permissions. The
clinician channel supports recommendations under 21 U.S.C. 360j(o)(1)(E); the patient channel
displays the patient's own data and their own clinician's own findings under (o)(1)(D), and
interprets nothing. Section 360j(o)(2) is what makes the split worth enforcing: where a product
holds one qualifying function and one that does not, only the latter is regulated as a device —
so the two functions have to be genuinely separable, not separable by intention.

`docs/GUARDRAILS.md` carries the full mapping and the reasoning. This module is where it binds.

The rule that shapes every decision below: a PatientView is built ONLY by projecting a
ClinicianView, the projection enumerates its fields by hand, and the projection is deliberately
LOSSY IN ONE DIRECTION. It cannot carry a predicted concentration, an interval, a boundary
verdict, an attribution, or any signal of WHICH WAY a level is moving. A patient message that
differed between "drifting low" and "drifting high" would be an interpretation delivered to the
patient, which is the thing the boundary exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from agent_pk.pk.fit import Prediction
from agent_pk.pk.variability import VariabilityReport
from agent_pk.pk.model import (
    DoseEvent,
    Observation,
    PkInputError,
    _require_finite,
    _require_non_negative_finite,
)

# ── Errors ───────────────────────────────────────────────────────────────────


class ChannelBoundaryError(PkInputError):
    """Raised when content would cross into a channel that may not carry it.

    Subclasses PkInputError so that a caller already handling malformed PK input handles a
    boundary breach too. A breach is a defect in this module or in a change to it, never a
    runtime condition to recover from.
    """


# ── The two closed vocabularies ──────────────────────────────────────────────


class ClinicalAction(StrEnum):
    """What the software may propose TO A CLINICIAN.

    Every member is a recommendation to a health care professional about the treatment of a
    condition, which is criterion 3 of 360j(o)(1)(E). None of these may be shown to a patient.
    """

    NO_ACTION = "no_action"
    FLAG_FOR_REVIEW = "flag_for_review"
    URGENT_REVIEW = "urgent_review"
    CONSIDER_DOSE_REDUCTION = "consider_dose_reduction"
    CONSIDER_DOSE_INCREASE = "consider_dose_increase"
    SCHEDULE_ADDITIONAL_PK_SAMPLE = "schedule_additional_pk_sample"
    ESCALATE_TO_TRANSPLANT_TEAM = "escalate_to_transplant_team"


class PatientMessage(StrEnum):
    """The COMPLETE set of things the software may say to a patient on its own account.

    A closed enum rather than a string field, because a string field is where an interpolated
    prediction eventually appears. The only prose in the patient channel that is not one of
    these is the clinician's OWN authored plan text, carried verbatim.
    """

    NOTHING_TO_DO = "nothing_to_do"
    CLINICIAN_NOTIFIED = "clinician_notified"
    SAMPLE_SCHEDULED = "sample_scheduled"
    CONTACT_YOUR_TEAM = "contact_your_team"
    EVALUATION_MAY_BE_HELPFUL = "evaluation_may_be_helpful"


PATIENT_MESSAGE_BODY: MappingProxyType[PatientMessage, str] = MappingProxyType(
    {
        PatientMessage.NOTHING_TO_DO: (
            "Nothing for you to do right now. Your next check is on schedule."
        ),
        PatientMessage.CLINICIAN_NOTIFIED: (
            "Your transplant team has been sent an update. They will be in touch if "
            "anything needs to change."
        ),
        PatientMessage.SAMPLE_SCHEDULED: (
            "A blood sample has been scheduled. The details are below, and I will walk you "
            "through it when the time comes."
        ),
        PatientMessage.CONTACT_YOUR_TEAM: (
            "Please contact your transplant team using the number they gave you."
        ),
        # The one primitive borrowed from FDA's General Wellness guidance (January 2026): a
        # general notification that an evaluation may be helpful. It names no condition, carries
        # no threshold, and calls nothing abnormal — which is exactly why it is permitted.
        PatientMessage.EVALUATION_MAY_BE_HELPFUL: (
            "Based on what you have told me, it may be helpful to have this looked at by "
            "your clinician."
        ),
    }
)


# ── The mapping, and the import-time completeness check ──────────────────────

_ACTION_TO_PATIENT_MESSAGE: MappingProxyType[ClinicalAction, PatientMessage] = (
    MappingProxyType(
        {
            ClinicalAction.NO_ACTION: PatientMessage.NOTHING_TO_DO,
            ClinicalAction.FLAG_FOR_REVIEW: PatientMessage.CLINICIAN_NOTIFIED,
            # URGENT_REVIEW deliberately collapses to the SAME message as FLAG_FOR_REVIEW.
            # Telling the patient that a review is urgent is both an interpretation and a
            # time-critical output — and under FDA's January 2026 guidance a time-critical
            # output is the thing that cannot permit independent review, so it is the thing
            # that makes software a device. Urgency is a fact about the clinician's queue.
            ClinicalAction.URGENT_REVIEW: PatientMessage.CLINICIAN_NOTIFIED,
            # Both dose directions collapse to one message. A patient who could tell "down"
            # from "up" has been told which way their level is moving, which is the
            # interpretation the patient channel may not make.
            ClinicalAction.CONSIDER_DOSE_REDUCTION: PatientMessage.CLINICIAN_NOTIFIED,
            ClinicalAction.CONSIDER_DOSE_INCREASE: PatientMessage.CLINICIAN_NOTIFIED,
            ClinicalAction.SCHEDULE_ADDITIONAL_PK_SAMPLE: PatientMessage.SAMPLE_SCHEDULED,
            ClinicalAction.ESCALATE_TO_TRANSPLANT_TEAM: PatientMessage.CONTACT_YOUR_TEAM,
        }
    )
)

# Fail CLOSED at import, not at first call. A new ClinicalAction member added without a patient
# mapping would otherwise raise only when that branch was first reached, which in a demo is on
# stage. Checking here means the module refuses to load at all.
if set(_ACTION_TO_PATIENT_MESSAGE) != set(ClinicalAction):
    _missing = sorted(
        a.value for a in set(ClinicalAction) - set(_ACTION_TO_PATIENT_MESSAGE)
    )
    raise ChannelBoundaryError(
        f"every ClinicalAction needs an explicit patient-channel mapping; missing: {_missing}"
    )

if set(PATIENT_MESSAGE_BODY) != set(PatientMessage):
    _bodyless = sorted(m.value for m in set(PatientMessage) - set(PATIENT_MESSAGE_BODY))
    raise ChannelBoundaryError(f"PatientMessage members without a body: {_bodyless}")


# ── Clinician-channel content ────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ParameterEstimate:
    """One fitted parameter with its credible interval, for the clinician to review.

    Criterion 4 requires the clinician to be able to review the BASIS of a recommendation. A
    point estimate is not a basis; a point estimate with its interval and the number of
    observations behind it is the beginning of one.
    """

    label: str
    value: float
    lower: float
    upper: float
    unit: str

    def __post_init__(self) -> None:
        _require_finite(self.value, "value")
        _require_finite(self.lower, "lower")
        _require_finite(self.upper, "upper")
        if not self.label or not self.unit:
            raise PkInputError("label and unit must be non-empty")
        if not self.lower <= self.value <= self.upper:
            raise PkInputError(
                f"{self.label}: estimate {self.value!r} must lie within "
                f"[{self.lower!r}, {self.upper!r}]"
            )


@dataclass(frozen=True, slots=True)
class Attribution:
    """How much of a change is attributed to one named factor, and on what authority.

    `magnitude_ng_per_ml` is None when the evidence supports a DIRECTION but not a size. That
    is the honest default for most interactions, and an absent magnitude must never be rendered
    as zero — it is a different statement.
    """

    factor: str
    direction: str
    magnitude_ng_per_ml: float | None
    source: str

    def __post_init__(self) -> None:
        if not self.factor or not self.source:
            raise PkInputError("factor and source must be non-empty")
        if self.direction not in ("raises", "lowers", "unexplained"):
            raise PkInputError(
                f"direction must be 'raises', 'lowers' or 'unexplained', "
                f"got {self.direction!r}"
            )
        if self.magnitude_ng_per_ml is not None:
            _require_finite(self.magnitude_ng_per_ml, "magnitude_ng_per_ml")


@dataclass(frozen=True, slots=True)
class EvidenceNote:
    """One cited claim, with the limits of the population it was derived in.

    `population_limit` is not optional decoration. FDA's January 2026 guidance makes the
    reliability of the clinical data driving an output part of what criterion 4 requires be
    reviewable, so a coefficient derived in a cohort that does not match this patient must say
    so where it is used, not in a footnote.
    """

    claim: str
    source_url: str
    population_limit: str | None = None

    def __post_init__(self) -> None:
        if not self.claim or not self.source_url:
            raise PkInputError("claim and source_url must be non-empty")


@dataclass(frozen=True, slots=True)
class ConcurrentObservation:
    """Something the CLINICIAN asks the patient to track alongside the blood samples.

    A blood level is one signal. A clinician looking at an unusual profile often wants the
    things that would EXPLAIN it — was the dose taken fasted, is the patient retaining fluid,
    did the weight move — recorded at the same time, because a covariate collected a week later
    cannot be matched to the curve it was supposed to explain.

    THE CONSTRAINT THAT MAKES THIS SAFE: the agent may not author one. `authored_by_clinician`
    must be True, and it is checked. An instruction a clinician wrote for their own patient is
    the clinician's own finding about their own patient, which 360j(o)(1)(D) expressly permits
    to be displayed verbatim. The same sentence generated by the software would be the software
    telling a patient what to do about their condition, which is the thing the patient channel
    may not do. The difference is authorship, so authorship is a field.

    Attributes:
        label: Short name shown in the patient's checklist, e.g. "Morning weight".
        instruction: The clinician's own words, carried verbatim to the patient.
        authored_by_clinician: Must be True. Present so that the agent cannot invent one.
    """

    label: str
    instruction: str
    authored_by_clinician: bool

    def __post_init__(self) -> None:
        if not self.label.strip() or not self.instruction.strip():
            raise PkInputError("label and instruction must not be empty")
        if self.authored_by_clinician is not True:
            raise ChannelBoundaryError(
                f"concurrent observation {self.label!r} is not clinician-authored; the agent "
                f"may propose WHICH blood samples to take, but only a clinician may tell a "
                f"patient what else to record about themselves"
            )


@dataclass(frozen=True, slots=True)
class SampleAppointment:
    """A proposed or booked sampling occasion. Logistics — safe in both channels.

    Attributes:
        start_time_h: When the sampling occasion begins, in hours since the patient's reference
            instant, on the same axis as DoseEvent and Observation.
        offsets_post_dose_h: The requested draw times relative to the dose, e.g. (0, 1, 3, 6).
        fasted_required: Whether the samples must be taken fasted. A high-fat meal lengthens
            tacrolimus Tmax roughly five-fold, so a fed post-dose sample measures a different
            curve — this is a precondition on the measurement, not a preference.
        concurrent_observations: What else the clinician wants recorded at the same time.
            Empty by default: an appointment that asks for nothing extra is the normal case,
            and the burden on the patient should rise only when a clinician decides it should.
    """

    start_time_h: float
    offsets_post_dose_h: tuple[float, ...]
    fasted_required: bool
    concurrent_observations: tuple[ConcurrentObservation, ...] = ()

    def __post_init__(self) -> None:
        _require_finite(self.start_time_h, "start_time_h")
        if not self.offsets_post_dose_h:
            raise PkInputError("offsets_post_dose_h must not be empty")
        for index, offset in enumerate(self.offsets_post_dose_h):
            _require_non_negative_finite(offset, f"offsets_post_dose_h[{index}]")
        if len(set(self.offsets_post_dose_h)) != len(self.offsets_post_dose_h):
            raise PkInputError("offsets_post_dose_h must not repeat a time")
        if list(self.offsets_post_dose_h) != sorted(self.offsets_post_dose_h):
            raise PkInputError("offsets_post_dose_h must be in ascending order")
        if isinstance(self.fasted_required, bool) is False:
            raise PkInputError("fasted_required must be a bool")
        labels = [obs.label for obs in self.concurrent_observations]
        if len(set(labels)) != len(labels):
            raise PkInputError("concurrent_observations must not repeat a label")

    @property
    def total_patient_burden(self) -> int:
        """Draws beyond the trough, plus things to record. What the patient actually experiences.

        Surfaced as one number because a clinician weighing a request on a patient's behalf is
        weighing the WHOLE ask, and a design that counts only the needles understates it.
        """
        extra_draws = sum(1 for offset in self.offsets_post_dose_h if offset > 0.0)
        return extra_draws + len(self.concurrent_observations)


@dataclass(frozen=True, slots=True)
class ClinicianView:
    """Everything the software shows a clinician: the recommendation AND its complete basis.

    The two are inseparable by construction — a ClinicianView cannot be built with an action
    but no basis, because `prediction`, `parameters` and `evidence` are required fields. That
    is criterion 4 expressed as a constructor signature rather than as a promise.

    Attributes:
        action: What the software proposes. A recommendation to a health care professional.
        prediction: The predicted interval and its boundary verdicts.
        parameters: This patient's fitted parameters with credible intervals.
        attributions: What is driving the change, and on whose authority.
        evidence: The citations behind every coefficient used, with their population limits.
        n_observations: How many measured concentrations the fit rests on. A small number is
            itself decision-relevant and is never hidden.
        calibration_note: Plain-English statement of how well this patient's own profile is
            resolved, and what more sampling would buy. The clinician decides whether to take it.
        variability: The patient's own intrapatient variability and time in therapeutic range,
            over the troughs available. None when the samples cannot support the measures —
            and when it is None, `variability_unavailable_reason` says why. The two are checked
            together in __post_init__ so that ABSENT can never be read as NORMAL, which is the
            defect this project has now produced twice (an unmeasured haematocrit defaulting to
            the reference value, and that same disclosure being dropped one layer down).
        variability_unavailable_reason: Why no variability figures are attached. Required to be
            non-empty exactly when `variability` is None, and required to be empty when it is
            not, so the two fields cannot disagree.
    """

    action: ClinicalAction
    prediction: Prediction
    parameters: tuple[ParameterEstimate, ...]
    attributions: tuple[Attribution, ...]
    evidence: tuple[EvidenceNote, ...]
    n_observations: int
    calibration_note: str
    proposed_sampling: SampleAppointment | None = None
    variability: VariabilityReport | None = None
    variability_unavailable_reason: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.n_observations, bool) or not isinstance(
            self.n_observations, int
        ):
            raise PkInputError("n_observations must be an int")
        if self.n_observations < 0:
            raise PkInputError("n_observations must be >= 0")
        if not self.parameters:
            raise ChannelBoundaryError(
                "a ClinicianView must carry the fitted parameters — a recommendation without "
                "its basis is the thing criterion 4 forbids"
            )
        if not self.evidence:
            raise ChannelBoundaryError(
                "a ClinicianView must carry its citations — the reliability of the evidence "
                "driving the output is part of what must be reviewable"
            )
        if (
            self.action is ClinicalAction.SCHEDULE_ADDITIONAL_PK_SAMPLE
            and self.proposed_sampling is None
        ):
            raise PkInputError(
                "SCHEDULE_ADDITIONAL_PK_SAMPLE requires a proposed_sampling appointment"
            )
        # Absent must never be readable as normal. A bare `variability=None` on a screen is
        # indistinguishable from "variability was measured and is fine", and that exact
        # ambiguity — an unmeasured value presenting as a reassuring one — is what a review
        # caught twice on the haematocrit path. Requiring the reason makes the silence speak.
        if self.variability is None and not self.variability_unavailable_reason.strip():
            raise ChannelBoundaryError(
                "variability is None but no reason was given. A missing measure shown without "
                "its reason reads as a reassuring one; state why it could not be computed "
                "(for example, fewer than the minimum troughs at distinct times)."
            )
        if self.variability is not None and self.variability_unavailable_reason:
            raise PkInputError(
                "variability_unavailable_reason must be empty when variability is present — "
                "the two fields would otherwise be free to disagree about the same fact"
            )


# ── Patient-channel content ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PatientView:
    """What a patient sees. Their own data, their clinician's own words, and logistics.

    Every field here is permitted by 360j(o)(1)(D): laboratory results, findings by a health
    care professional with respect to those results, and general background — provided the
    function does not itself interpret them.

    `own_results` carries the patient's own RETURNED laboratory values, which is squarely what
    (D) contemplates. It never carries a prediction: the type is `Observation`, which is by
    definition a measured concentration from a laboratory report, and a `Prediction` is a
    structurally different type that this view has no field to hold.

    If the patient reads their own returned result alongside the range their own clinician
    wrote for them and draws a conclusion, that is the patient reading their chart. The
    software has still interpreted nothing, which is the distinction (D) turns on.

    THE SET OF FIELDS BELOW IS THE PERMISSION BOUNDARY. A test asserts it exactly, so widening
    it is a deliberate act that fails the suite until someone reviews the change.
    """

    message: PatientMessage
    plan_text_from_clinician: str
    own_doses: tuple[DoseEvent, ...]
    own_results: tuple[Observation, ...]
    next_sample: SampleAppointment | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.message, PatientMessage):
            raise ChannelBoundaryError(
                "message must be a PatientMessage member — free text in the patient channel "
                "is where an interpolated prediction eventually appears"
            )

    @property
    def body(self) -> str:
        """The rendered message text for this view."""
        return PATIENT_MESSAGE_BODY[self.message]


# The permitted field set, named once so the projection and its test share one source.
PATIENT_VIEW_FIELDS: frozenset[str] = frozenset(
    {
        "message",
        "plan_text_from_clinician",
        "own_doses",
        "own_results",
        "next_sample",
    }
)


# ── The projection ───────────────────────────────────────────────────────────


def to_patient_view(
    clinician_view: ClinicianView,
    *,
    plan_text_from_clinician: str,
    own_doses: tuple[DoseEvent, ...],
    own_results: tuple[Observation, ...],
) -> PatientView:
    """Project a ClinicianView into the patient channel, discarding everything not permitted.

    The fields are enumerated by hand and NOT copied wholesale. That is deliberate: a
    `dataclasses.asdict` or `**vars()` construction would silently carry any field added to
    ClinicianView later into the patient channel, and the whole point of this boundary is that
    widening it has to be a decision somebody makes on purpose.

    Args:
        clinician_view: The full view. Only its `action` and, for a sampling action, its
            `proposed_sampling` survive the projection.
        plan_text_from_clinician: Text a clinician authored for this patient. Carried verbatim
            — it is the clinician's own finding about their own patient, which (o)(1)(D)
            expressly permits, and it is not the software speaking.
        own_doses: The patient's own logged doses.
        own_results: The patient's own returned laboratory concentrations. Measurements only.

    Returns:
        A PatientView carrying no prediction, no interval, no boundary verdict, no attribution
        and no direction of travel.

    Raises:
        ChannelBoundaryError: If the action has no patient mapping. Unreachable while the
            import-time check holds, and kept as a second line because this is the function a
            future change is most likely to break.
    """
    try:
        message = _ACTION_TO_PATIENT_MESSAGE[clinician_view.action]
    except KeyError as exc:
        raise ChannelBoundaryError(
            f"no patient-channel mapping for action {clinician_view.action!r}"
        ) from exc

    # The appointment crosses ONLY when the action is to schedule one. A proposal the clinician
    # has not accepted must not appear on the patient's phone as though it were booked.
    next_sample = (
        clinician_view.proposed_sampling
        if clinician_view.action is ClinicalAction.SCHEDULE_ADDITIONAL_PK_SAMPLE
        else None
    )

    return PatientView(
        message=message,
        plan_text_from_clinician=plan_text_from_clinician,
        own_doses=own_doses,
        own_results=own_results,
        next_sample=next_sample,
    )


def general_evaluation_notice(
    *,
    plan_text_from_clinician: str,
    own_doses: tuple[DoseEvent, ...],
    own_results: tuple[Observation, ...],
) -> PatientView:
    """The patient-initiated path: a general notice that an evaluation may be helpful.

    Used when a patient reports feeling unwell and no clinician-channel action has been
    produced. It names no condition, carries no threshold and calls nothing abnormal, which is
    what keeps it inside the general-wellness notification primitive rather than turning it
    into an interpretation.

    Args:
        plan_text_from_clinician: The clinician's own authored text, carried verbatim.
        own_doses: The patient's own logged doses.
        own_results: The patient's own returned laboratory concentrations.

    Returns:
        A PatientView carrying only the general notice.
    """
    return PatientView(
        message=PatientMessage.EVALUATION_MAY_BE_HELPFUL,
        plan_text_from_clinician=plan_text_from_clinician,
        own_doses=own_doses,
        own_results=own_results,
        next_sample=None,
    )
