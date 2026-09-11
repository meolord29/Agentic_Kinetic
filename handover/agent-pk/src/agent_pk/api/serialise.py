"""serialise.py — turn the domain views into JSON, one field at a time.

EVERY FIELD IS ENUMERATED BY HAND AND NOTHING IS COPIED WHOLESALE. A `dataclasses.asdict` or a
`**vars()` would carry any field added to `ClinicianView` later straight onto the wire, and for
the patient projection that is the entire hazard: the boundary exists so that widening it is a
decision somebody makes on purpose. The same argument `to_patient_view` makes for its own
construction applies with equal force to its serialiser, which is the last place a field can
escape.

The patient serialiser is the narrow one. It emits the five permitted fields and asserts that
set against `PATIENT_VIEW_FIELDS`, so a field added to `PatientView` without a matching decision
here fails loudly rather than appearing in a response.
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any

from agent_pk.agent.case import PatientCase
from agent_pk.agent.evaluate import PARAMETER_INTERVAL_MASS
from agent_pk.channel import (
    PATIENT_VIEW_FIELDS,
    ChannelBoundaryError,
    ClinicianView,
    PatientView,
    SampleAppointment,
)
from agent_pk.pk.fit import Prediction
from agent_pk.pk.model import DoseEvent, Observation, PkInputError
from agent_pk.pk.priors import (
    SOURCE_CITATION,
    SOURCE_POPULATION_LIMIT,
    SOURCE_URL,
    PopulationPrior,
)
from agent_pk.pk.variability import VariabilityReport

#: The `PatientView` FIELDS this serialiser reads — not the keys it emits, which additionally
#: carry `body`, the rendered text of the `message` enum. Compared against the channel's own
#: permitted set at call time, so a field added to the view without a decision here fails loudly.
_PATIENT_KEYS: frozenset[str] = frozenset(
    {"message", "plan_text_from_clinician", "own_doses", "own_results", "next_sample"}
)


def _dose_json(dose: DoseEvent) -> dict[str, Any]:
    """One dose event as JSON."""
    return {
        "time_h": dose.time_h,
        "amount_mg": dose.amount_mg,
        "status": dose.status,
    }


def _observation_json(observation: Observation) -> dict[str, Any]:
    """One measured concentration as JSON. A measurement, never a prediction."""
    return {
        "time_h": observation.time_h,
        "concentration_ng_per_ml": observation.concentration_ng_per_ml,
    }


def _appointment_json(appointment: SampleAppointment) -> dict[str, Any]:
    """A sampling appointment as JSON. Logistics — permitted in both channels."""
    return {
        "start_time_h": appointment.start_time_h,
        "offsets_post_dose_h": list(appointment.offsets_post_dose_h),
        "fasted_required": appointment.fasted_required,
        "concurrent_observations": [
            {
                "label": observation.label,
                "instruction": observation.instruction,
                "authored_by_clinician": observation.authored_by_clinician,
            }
            for observation in appointment.concurrent_observations
        ],
        "total_patient_burden": appointment.total_patient_burden,
    }


def _prediction_json(prediction: Prediction) -> dict[str, Any]:
    """The predicted interval and its verdicts. CLINICIAN CHANNEL ONLY."""
    return {
        "time_h": prediction.time_h,
        "median_ng_per_ml": prediction.median_ng_per_ml,
        "lower_ng_per_ml": prediction.lower_ng_per_ml,
        "upper_ng_per_ml": prediction.upper_ng_per_ml,
        "interval_mass": prediction.credible_mass,
        "crosses_below": prediction.crosses_below,
        "crosses_above": prediction.crosses_above,
        "crosses_boundary": prediction.crosses_boundary,
        "probability_below": prediction.probability_below,
        "probability_above": prediction.probability_above,
        "usable_fraction": prediction.usable_fraction,
        "haematocrit_known": prediction.haematocrit_known,
        "interval_note": (
            "A PREDICTION interval for a future measured trough — what the laboratory will "
            "report — not a credible interval on the typical value. It is the wider of the "
            "two, and it is the one a therapeutic range is written against."
        ),
    }


def prediction_json(prediction: Prediction) -> dict[str, Any]:
    """The predicted interval a run was gated on, for a response outside `clinician_view`.

    CLINICIAN CHANNEL ONLY. Exposed so a paused run can report the prediction that raised its
    offer: the decision card is drawn BEFORE anyone answers, so the reasons for the question must
    arrive with the question rather than only after it has been answered.

    Args:
        prediction: The prediction.

    Returns:
        JSON-serialisable dict, identical in shape to `clinician_view.prediction`.
    """
    return _prediction_json(prediction)


def variability_json(report: VariabilityReport | None) -> dict[str, Any] | None:
    """Intrapatient variability and time in range as JSON, or None when unavailable.

    None is returned as None, never as zeros. The reason it is unavailable travels in its own
    field beside it, and a renderer must show that reason — an absent measure displayed without
    one reads as a reassuring one.

    Args:
        report: The variability report, or None.

    Returns:
        JSON-serialisable dict, or None.
    """
    if report is None:
        return None
    return {
        "ipv_percent": report.ipv_percent,
        "ipv_is_high": report.ipv_is_high,
        "time_in_range_percent": report.time_in_range_percent,
        "n_samples": report.n_samples,
        "span_h": report.span_h,
    }


def population_reference_json(prior: PopulationPrior) -> dict[str, Any]:
    """Where patients like this one sit on apparent clearance. CLINICIAN CHANNEL ONLY.

    THE NUMBERS COME FROM THE SAME COVARIATE-ADJUSTED PRIOR THE FIT WAS PULLED TOWARD, not from a
    second copy of the published estimates, so the comparison a board draws cannot describe a
    different population from the one the patient was evaluated against. `typical` is the prior's
    central clearance on the log scale it is defined on; `lower` and `upper` enclose the central
    PARAMETER_INTERVAL_MASS of between-patient variability around it — the same mass as the
    prediction interval and the fitted parameter intervals on the same screen.

    `population_limit` travels WITH the numbers rather than in a footnote: the source cohort was de
    novo and early after transplant, and a comparison shown without that limit reads as a statement
    about maintenance patients that the source never made. `genotype_known` is carried because an
    unknown CYP3A5 genotype widens and shifts this reference, and a renderer should say so.

    Args:
        prior: The covariate-adjusted population prior for this patient.

    Returns:
        JSON-serialisable dict.

    Raises:
        PkInputError: If any figure is not a positive finite clearance. Unreachable for a prior
            `prior_for` built, which already refuses a non-positive clearance; checked here
            because this is the last layer before a number is drawn on a clinician's screen.
    """
    z = NormalDist().inv_cdf(0.5 + PARAMETER_INTERVAL_MASS / 2.0)
    centre, spread = prior.log_clearance_mean, prior.omega_log_clearance
    figures = {
        "typical": math.exp(centre),
        "lower": math.exp(centre - z * spread),
        "upper": math.exp(centre + z * spread),
    }
    for name, value in figures.items():
        if not math.isfinite(value) or value <= 0.0:
            raise PkInputError(
                f"population reference {name} is not a positive finite clearance: {value!r}"
            )
    return {
        "label": "Apparent clearance (CL/F)",
        "unit": "L/h",
        **figures,
        "interval_mass": PARAMETER_INTERVAL_MASS,
        "genotype_known": prior.genotype_known,
        "source": SOURCE_CITATION,
        "source_url": SOURCE_URL,
        "population_limit": SOURCE_POPULATION_LIMIT,
    }


def clinician_context_json(case: PatientCase, prior: PopulationPrior) -> dict[str, Any]:
    """What a clinician's board draws this patient's numbers against. CLINICIAN CHANNEL ONLY.

    The care plan's bounds, the patient's own measured troughs, curve samples and dose log, and the
    population reference. Nothing here is new clinical content — every value is already an input
    to, or the prior of, the evaluation the response reports — but without it a renderer has to
    parse the bounds out of evidence prose and fetch measurements from a second route.

    DELIBERATELY NOT A FIELD OF `ClinicianView`. That type is what the patient projection is built
    from, so widening it widens the source of the permission boundary; this block is assembled at
    the HTTP layer from the run's own inputs and never passes through `to_patient_view`.

    Args:
        case: The evaluation's inputs.
        prior: The covariate-adjusted prior the fit used.

    Returns:
        JSON-serialisable dict.
    """
    return {
        "plan": {
            "lower_bound_ng_per_ml": case.plan.lower_bound_ng_per_ml,
            "upper_bound_ng_per_ml": case.plan.upper_bound_ng_per_ml,
            "band_citation": case.plan.band_citation,
        },
        "own_troughs": [_observation_json(obs) for obs in case.troughs],
        "own_curve_samples": [_observation_json(obs) for obs in case.curve_samples],
        "own_doses": [_dose_json(dose) for dose in case.doses],
        "target_time_h": case.target_time_h,
        "next_dose_time_h": case.next_dose_time_h,
        "population_reference": population_reference_json(prior),
    }


def clinician_view_json(view: ClinicianView) -> dict[str, Any]:
    """The full clinician payload: the recommendation AND its complete basis.

    Args:
        view: The view to serialise.

    Returns:
        JSON-serialisable dict. Carries the basis in full — a recommendation serialised without
        it would be exactly what criterion 4 forbids, arriving one layer below the constructor
        that refuses to build it.
    """
    return {
        "action": str(view.action),
        "prediction": _prediction_json(view.prediction),
        "parameters": [
            {
                "label": parameter.label,
                "value": parameter.value,
                "lower": parameter.lower,
                "upper": parameter.upper,
                "unit": parameter.unit,
            }
            for parameter in view.parameters
        ],
        "attributions": [
            {
                "factor": attribution.factor,
                "direction": attribution.direction,
                "magnitude_ng_per_ml": attribution.magnitude_ng_per_ml,
                "source": attribution.source,
            }
            for attribution in view.attributions
        ],
        "evidence": [
            {
                "claim": note.claim,
                "source_url": note.source_url,
                "population_limit": note.population_limit,
            }
            for note in view.evidence
        ],
        "n_observations": view.n_observations,
        "calibration_note": view.calibration_note,
        "proposed_sampling": (
            _appointment_json(view.proposed_sampling)
            if view.proposed_sampling is not None
            else None
        ),
        "variability": variability_json(view.variability),
        "variability_unavailable_reason": view.variability_unavailable_reason,
    }


def patient_view_json(view: PatientView) -> dict[str, Any]:
    """The patient payload: five permitted fields and nothing else.

    Args:
        view: The projection to serialise.

    Returns:
        JSON-serialisable dict carrying no prediction, no interval, no boundary verdict, no
        attribution and no direction of travel.

    Raises:
        ChannelBoundaryError: If `PatientView` has gained or lost a field since this serialiser
            was written. Widening the patient channel must be a deliberate act, and a silent
            mismatch here is how it would stop being one.
    """
    if _PATIENT_KEYS != PATIENT_VIEW_FIELDS:
        raise ChannelBoundaryError(
            "the patient serialiser and the channel's permitted field set disagree: "
            f"serialiser={sorted(_PATIENT_KEYS)!r} channel={sorted(PATIENT_VIEW_FIELDS)!r}. "
            "Reconcile them deliberately — this is the permission boundary."
        )
    return {
        # The message is chosen from a closed enum and its body is a fixed string. It is the
        # only prose here the software authors, and it contains no digits by construction.
        "message": str(view.message),
        "body": view.body,
        # The clinician's OWN words about their OWN patient, carried verbatim. Permitted under
        # 360j(o)(1)(D) precisely because the software did not write it.
        "plan_text_from_clinician": view.plan_text_from_clinician,
        "own_doses": [_dose_json(dose) for dose in view.own_doses],
        "own_results": [_observation_json(result) for result in view.own_results],
        "next_sample": (
            _appointment_json(view.next_sample)
            if view.next_sample is not None
            else None
        ),
    }
