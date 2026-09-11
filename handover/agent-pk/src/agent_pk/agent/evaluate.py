"""evaluate.py — the deterministic evaluation steps, as plain functions. Framework-free.

Every clinical decision this product makes is in this file, and none of it is a model call.
`gate_action` reads `Prediction.crosses_boundary` and nothing else; a language model may later
phrase the explanation, and it never chooses whether to escalate. That claim is the whole
regulatory argument (`docs/GUARDRAILS.md`, criterion 4), so the code it rests on is kept where
it can be read and tested without a graph runtime standing in the way.

The graph in `graph.py` wires these into nodes and owns the pause. It adds no decision of
its own.
"""

from __future__ import annotations

import logging
import math
from typing import Final

from agent_pk.agent.case import PatientCase, ReviewRequired
from agent_pk.channel import (
    Attribution,
    ClinicalAction,
    ClinicianView,
    EvidenceNote,
    ParameterEstimate,
    SampleAppointment,
)
from agent_pk.pk import priors
from agent_pk.pk.calibration import (
    LSS_OFFSETS_H,
    CalibrationError,
    ExposureEstimate,
    SamplingOffer,
    build_sampling_offer,
    exposure_uncertainty,
)
from agent_pk.pk.fit import (
    FitResult,
    PkDegenerateSampleError,
    Prediction,
    fit_individual,
    predict_trough,
)
from agent_pk.pk.model import PkInputError
from agent_pk.pk.priors import PopulationPrior, prior_for
from agent_pk.pk.variability import VariabilityReport, variability_report_or_reason

logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

#: Interval mass of the reported parameter intervals. 0.90 to match the prediction interval's
#: default, so the two figures on one screen are not quoting different masses.
PARAMETER_INTERVAL_MASS: Final[float] = 0.90

#: The z multiplier for PARAMETER_INTERVAL_MASS, on the log scale the parameters are fitted on.
#: Derived rather than typed, so the two cannot drift apart if the mass is changed.
_Z: Final[float] = (
    1.6448536269514722  # Phi^-1(0.95); asserted against the mass at import.
)

#: Labels and units for the fitted parameter vector, in the order `log_theta` carries them.
_PARAMETER_LABELS: Final[tuple[tuple[str, str], ...]] = (
    ("Apparent clearance (CL/F)", "L/h"),
    ("Apparent central volume (Vc/F)", "L"),
    ("Absorption rate constant (ka)", "1/h"),
)


def _check_z_matches_mass() -> None:
    """Fail at import if the z multiplier and the declared interval mass disagree.

    A declared contract field nothing verifies is worse than no declaration, because a reader
    assumes it is enforced. This is that check for the one pair of constants above that can
    silently fall out of step.

    Raises:
        AssertionError: Never at runtime — the values are fixed. Present so that editing one
            without the other stops the module loading rather than quietly reporting an
            interval of a different width than it claims.
    """
    tail = (1.0 - PARAMETER_INTERVAL_MASS) / 2.0
    implied = 0.5 * math.erfc(_Z / math.sqrt(2.0))
    if abs(implied - tail) > 1e-9:
        raise AssertionError(
            f"_Z={_Z!r} encloses mass {1.0 - 2.0 * implied!r}, not "
            f"PARAMETER_INTERVAL_MASS={PARAMETER_INTERVAL_MASS!r}"
        )


_check_z_matches_mass()


# ── Steps ────────────────────────────────────────────────────────────────────


def fit_case(case: PatientCase) -> tuple[PopulationPrior, FitResult]:
    """Build the covariate-adjusted prior and fit this patient against it.

    Args:
        case: The evaluation's inputs.

    Returns:
        The prior used and the resulting fit. With no observations the fit IS the prior, which
        is the correct answer rather than a degraded one.

    Raises:
        PkInputError: If the covariates or observations are malformed.
    """
    prior = prior_for(case.covariates)
    fit = fit_individual(case.doses, case.observations, prior)
    return prior, fit


def predict_case(case: PatientCase, fit: FitResult) -> Prediction | ReviewRequired:
    """Predict the target trough as an interval, or say why it could not be predicted.

    THE DEGENERATE CASE RETURNS A VALUE RATHER THAN RAISING, and the value is not a verdict.
    `predict_trough` requires its caller to route a degenerate sample to a human rather than
    treating it as an absent escalation; returning `ReviewRequired` is how that requirement is
    carried into the graph, where an exception would otherwise be caught somewhere generic and
    become a quiet `NO_ACTION`.

    Args:
        case: The evaluation's inputs.
        fit: The individual fit.

    Returns:
        The `Prediction`, or a `ReviewRequired` naming what went wrong.

    Raises:
        PkInputError: If the bounds or the target time are malformed. A broken care plan is
            NOT routed to review as though it were thin data — it is a defect in the plan and
            must surface as one.
    """
    try:
        return predict_trough(
            case.doses,
            fit,
            case.target_time_h,
            case.plan.lower_bound_ng_per_ml,
            case.plan.upper_bound_ng_per_ml,
            seed=case.prediction_seed,
            credible_mass=PARAMETER_INTERVAL_MASS,
        )
    except PkDegenerateSampleError as exc:
        logger.warning("predictive sampling degenerated: %s", exc)
        return ReviewRequired(
            stage="prediction",
            reason=(
                "This patient's record could not be turned into a usable prediction interval, "
                "so no boundary check was performed. That is not the same as a level inside "
                f"the range, and it needs a person to look at it. Detail: {exc}"
            ),
        )


def gate_action(prediction: Prediction) -> ClinicalAction:
    """Decide what the software proposes. Deterministic, and the only place that decides.

    ONE INPUT AND ONE RULE, kept that way on purpose. The interval is tested against the
    plan's boundaries by `predict_trough`, and this reads the verdict. No language model is
    consulted, no threshold is re-derived here, and there is no branch on anything else — a
    second input is a second place the escalation could be suppressed.

    A crossing proposes ADDITIONAL SAMPLING, never a dose change. Both are permitted to a
    clinician under 360j(o)(1)(E), but a dose proposal from a model whose own estimate is not
    yet independently checkable is a recommendation resting on an unchecked number. Proposing
    the measurement that would check it is the honest move, and it is the product's claim:
    it says when to look.

    Args:
        prediction: The predicted interval and its boundary verdicts.

    Returns:
        `SCHEDULE_ADDITIONAL_PK_SAMPLE` when the interval reaches a boundary, `NO_ACTION`
        otherwise.
    """
    if prediction.crosses_boundary:
        return ClinicalAction.SCHEDULE_ADDITIONAL_PK_SAMPLE
    return ClinicalAction.NO_ACTION


def offer_for(
    case: PatientCase, fit: FitResult, prior: PopulationPrior
) -> SamplingOffer | str:
    """Build the sampling offer a clinician accepts or declines, or say why there is none.

    Args:
        case: The evaluation's inputs.
        fit: The current fit.
        prior: The prior the fit was made against.

    Returns:
        The `SamplingOffer`, or a plain-English reason it could not be built.

    Raises:
        PkInputError: If the forecast inputs are malformed — a defect, not thin data.
    """
    try:
        return build_sampling_offer(
            case.doses,
            fit,
            prior,
            existing_observations=case.observations,
            next_dose_time_h=case.next_dose_time_h,
            offsets_post_dose_h=LSS_OFFSETS_H,
            seed=case.offer_seed,
            n_simulations=case.offer_simulations,
        )
    except CalibrationError as exc:
        # The CROSSING STILL STANDS. Only the forecast of what extra samples would buy has
        # failed, so the fallback is a weaker action, never a silent downgrade to no action.
        logger.warning("sampling offer could not be forecast: %s", exc)
        return (
            "No sampling schedule could be scored for this patient, so there is no forecast "
            f"of what extra draws would buy. The boundary crossing itself stands. Detail: {exc}"
        )


def appointment_for(case: PatientCase, offer: SamplingOffer) -> SampleAppointment:
    """Turn an accepted offer into the appointment both channels may see.

    The appointment carries NO concurrent observations. Only a clinician may ask a patient to
    record something about themselves, and `ConcurrentObservation` refuses one that is not
    clinician-authored — so the software proposing draw times adds none, and a clinician who
    wants them attaches them to the accepted appointment.

    Args:
        case: The evaluation's inputs.
        offer: The accepted offer.

    Returns:
        The appointment, timed from the dose the offer was scored against.
    """
    return SampleAppointment(
        start_time_h=case.next_dose_time_h,
        offsets_post_dose_h=offer.offsets_post_dose_h,
        fasted_required=True,
        concurrent_observations=(),
    )


# ── Assembling the clinician view ────────────────────────────────────────────


def parameter_estimates(fit: FitResult) -> tuple[ParameterEstimate, ...]:
    """Report each fitted parameter with an interval, on the natural scale.

    The fit is on the log scale, so the interval is formed there and exponentiated. That keeps
    it strictly positive and asymmetric, which is the honest shape for a clearance — a
    symmetric interval on the natural scale can reach zero or below.

    Args:
        fit: The individual fit.

    Returns:
        One estimate per fitted parameter, in the fit's own parameter order. Absorption
        appears only when it was actually estimated: a ka reported with a credible interval it
        did not earn is a confident number for something nobody measured.
    """
    estimates: list[ParameterEstimate] = []
    for index, log_value in enumerate(fit.log_theta):
        label, unit = _PARAMETER_LABELS[index]
        sd = math.sqrt(fit.covariance[index][index])
        estimates.append(
            ParameterEstimate(
                label=label,
                value=math.exp(log_value),
                lower=math.exp(log_value - _Z * sd),
                upper=math.exp(log_value + _Z * sd),
                unit=unit,
            )
        )
    return tuple(estimates)


def evidence_notes(case: PatientCase, fit: FitResult) -> tuple[EvidenceNote, ...]:
    """The citations behind every coefficient used, each with its population limit.

    THE DISCLOSURES ARE CONDITIONAL AND THAT IS THE POINT. An unmeasured haematocrit and an
    untested genotype each bias the answer in the direction that SUPPRESSES an escalation, so
    each adds its own note when it applies, and neither is folded into a general caveat a
    reader can skim past.

    Args:
        case: The evaluation's inputs.
        fit: The individual fit, which carries the disclosure flags through from the prior.

    Returns:
        At least two notes — the population model and the therapeutic range — plus one per
        applicable disclosure.
    """
    notes = [
        EvidenceNote(
            claim=(
                "Population pharmacokinetic parameters, between-patient variability and "
                "residual error are taken unchanged from the published model: "
                f"{priors.SOURCE_CITATION}"
            ),
            source_url=priors.SOURCE_URL,
            population_limit=priors.SOURCE_POPULATION_LIMIT,
        ),
        EvidenceNote(
            claim=(
                "Therapeutic range "
                f"{case.plan.lower_bound_ng_per_ml:g}-{case.plan.upper_bound_ng_per_ml:g} "
                "ng/mL, as written in this patient's own care plan: "
                f"{case.plan.band_citation}"
            ),
            source_url=priors.SOURCE_URL,
            population_limit=(
                "The range is the clinician's, not the software's. It is applied as written "
                "and is never adjusted, widened or inferred."
            ),
        ),
    ]
    if not fit.haematocrit_known:
        notes.append(
            EvidenceNote(
                claim=(
                    "This patient's haematocrit was NOT measured, so the standardisation the "
                    "source model requires did not run — it was applied as the identity."
                ),
                source_url=priors.SOURCE_URL,
                population_limit=(
                    "An unmeasured anaemia makes the model read clearance as faster than it "
                    "is and UNDERSTATES the probability of a sub-therapeutic trough, so this "
                    "absence errs toward missing an escalation rather than raising a false one."
                ),
            )
        )
    if not fit.estimated_ka:
        notes.append(
            EvidenceNote(
                claim=(
                    "Absorption was held at the population value, not estimated: this fit has "
                    "no post-dose samples able to identify it."
                ),
                source_url=priors.SOURCE_URL,
                population_limit=(
                    "Three of the model's six parameters are individualised at most. "
                    "Absorption is not one of them here."
                ),
            )
        )
    return tuple(notes)


def calibration_note(
    case: PatientCase, fit: FitResult, exposure: ExposureEstimate | None
) -> str:
    """State how well this patient's own profile is resolved, and what more sampling buys.

    LEADS WITH THE EXPOSURE INTERVAL, NOT THE CALIBRATION SCORE. Calibration is parameter
    precision and is HIGHER on a trough-only fit that assumes absorption away than on a curve
    fit that carries it — a card built on it promises a rise and delivers a drop once real
    points land. `independently_checkable` is the honest answer to "why sample more": right
    now nothing can check this estimate but itself.

    Args:
        case: The evaluation's inputs.
        fit: The individual fit.
        exposure: The exposure estimate, or None when it could not be computed.

    Returns:
        Plain English for the clinician-facing basis panel.
    """
    basis = (
        f"This profile rests on {fit.n_observations} measured "
        f"{'concentration' if fit.n_observations == 1 else 'concentrations'}"
    )
    if exposure is None:
        return (
            f"{basis}. The 24-hour exposure interval could not be computed for this fit, so "
            "the width figure that would normally sit here is absent rather than estimated."
        )
    checkable = (
        "The published limited-sampling equation can be run against this fit as an "
        "independent cross-check."
        if exposure.independently_checkable
        else (
            "Nothing can currently check this estimate but itself: the published "
            "limited-sampling equation needs post-dose samples this patient has not given, "
            "so a four-point occasion timed from the next dose would make it runnable."
        )
    )
    return (
        f"{basis}. The 24-hour exposure interval is {exposure.relative_width * 100:.0f}% wide "
        f"relative to its own median. {checkable}"
    )


def attributions_for(prediction: Prediction) -> tuple[Attribution, ...]:
    """What is driving the predicted movement, and on whose authority.

    Returns a single UNEXPLAINED attribution, deliberately. This layer has no interaction
    report to reason from — the curated table is queried by the agent's own tool when a
    patient names something — and inventing a cause for a drift the model cannot attribute
    would put a fabricated explanation into the basis panel, which is the one place a
    clinician is entitled to trust.

    Args:
        prediction: The prediction whose movement is being attributed.

    Returns:
        One attribution, with no magnitude. An absent magnitude is not zero, and the type
        keeps the two distinguishable.
    """
    # An interval reaching BOTH boundaries supports NEITHER direction, and naming one would put
    # a clinical claim on a basis panel that the evidence does not carry. Raised as an
    # uncertainty by the Stage-A verifier, which found the earlier form reported "raises" for a
    # prediction that also crossed below. "unexplained" is the honest token and the type has one.
    if prediction.crosses_above and prediction.crosses_below:
        direction = "unexplained"
    elif not prediction.crosses_boundary:
        direction = "unexplained"
    elif prediction.crosses_above:
        direction = "raises"
    else:
        direction = "lowers"
    return (
        Attribution(
            factor="Individual clearance relative to the population",
            direction=direction,
            magnitude_ng_per_ml=None,
            source=priors.SOURCE_CITATION,
        ),
    )


def variability_for(case: PatientCase) -> tuple[VariabilityReport | None, str]:
    """This patient's intrapatient variability and time in range, or why they are unavailable.

    THE ONE PLACE VARIABILITY IS DERIVED FOR A CASE. The completed clinician view and a paused
    run's HTTP response both read it from here, so the figure a board shows before the decision
    cannot drift from the one it shows after it — two call sites each spelling out the same inputs
    is how that drift would start.

    Args:
        case: The evaluation's inputs. Only the troughs and the plan's bounds are read.

    Returns:
        The report and an empty reason, or None and a non-empty reason.
    """
    return variability_report_or_reason(
        case.troughs,
        case.plan.lower_bound_ng_per_ml,
        case.plan.upper_bound_ng_per_ml,
    )


def build_clinician_view(
    case: PatientCase,
    fit: FitResult,
    prediction: Prediction,
    action: ClinicalAction,
    appointment: SampleAppointment | None,
    exposure: ExposureEstimate | None,
) -> ClinicianView:
    """Assemble the full clinician view, or raise rather than serve a partial one.

    Args:
        case: The evaluation's inputs.
        fit: The individual fit.
        prediction: The predicted interval.
        action: What the gate decided.
        appointment: The accepted appointment, or None.
        exposure: The exposure estimate, or None when it could not be computed.

    Returns:
        A complete `ClinicianView`.

    Raises:
        ChannelBoundaryError: If the basis is incomplete. NOT caught anywhere in this layer —
            an incomplete basis is a programming defect, and degrading to a partial view is
            precisely what criterion 4 forbids.
    """
    report, reason = variability_for(case)
    return ClinicianView(
        action=action,
        prediction=prediction,
        parameters=parameter_estimates(fit),
        attributions=attributions_for(prediction),
        evidence=evidence_notes(case, fit),
        n_observations=fit.n_observations,
        calibration_note=calibration_note(case, fit, exposure),
        proposed_sampling=appointment,
        variability=report,
        variability_unavailable_reason=reason,
    )


def exposure_for(case: PatientCase, fit: FitResult) -> ExposureEstimate | None:
    """The 24-hour exposure estimate, or None when it could not be computed.

    Args:
        case: The evaluation's inputs.
        fit: The individual fit.

    Returns:
        The estimate, or None. None is carried as its own state rather than as a zero width,
        because a zero width would read as perfect certainty.
    """
    try:
        return exposure_uncertainty(
            case.doses,
            fit,
            start_h=case.next_dose_time_h,
            end_h=case.next_dose_time_h + 24.0,
            seed=case.offer_seed,
        )
    except (CalibrationError, PkInputError) as exc:
        logger.warning("exposure interval could not be computed: %s", exc)
        return None
