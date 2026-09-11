"""Tacrolimus pharmacokinetic core for Agent PK.

Directional, not diagnostic. This package predicts a concentration INTERVAL and reports
whether that interval crosses a boundary written by a clinician. It never recommends a dose.
"""

from __future__ import annotations

from agent_pk.pk.calibration import (
    LSS_OFFSETS_H,
    AucCrossCheck,
    CalibrationError,
    ExposureEstimate,
    SamplingOffer,
    auc_cross_check,
    build_sampling_offer,
    expected_calibration_after,
    expected_exposure_width_after,
    exposure_uncertainty,
    profile_calibration,
    published_auc_from_curve,
)
from agent_pk.pk.fit import (
    FitResult,
    Prediction,
    absorption_is_identifiable,
    count_absorption_informative_observations,
    fit_individual,
    predict_trough,
)
from agent_pk.pk.model import (
    DoseEvent,
    Observation,
    PkParameters,
    auc_over_interval,
    concentration_at,
)
from agent_pk.pk.priors import (
    KA_PER_H,
    LAG_H,
    SOURCE_CITATION,
    SOURCE_POPULATION_LIMIT,
    Covariates,
    Formulation,
    PopulationPrior,
    prior_for,
)

__all__ = [
    "KA_PER_H",
    "LAG_H",
    "SOURCE_CITATION",
    "SOURCE_POPULATION_LIMIT",
    "LSS_OFFSETS_H",
    "AucCrossCheck",
    "CalibrationError",
    "Covariates",
    "ExposureEstimate",
    "Formulation",
    "SamplingOffer",
    "DoseEvent",
    "FitResult",
    "Observation",
    "PkParameters",
    "PopulationPrior",
    "Prediction",
    "absorption_is_identifiable",
    "auc_cross_check",
    "auc_over_interval",
    "build_sampling_offer",
    "concentration_at",
    "count_absorption_informative_observations",
    "expected_calibration_after",
    "expected_exposure_width_after",
    "exposure_uncertainty",
    "fit_individual",
    "profile_calibration",
    "published_auc_from_curve",
    "predict_trough",
    "prior_for",
]
