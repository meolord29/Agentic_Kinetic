"""case.py — the typed inputs and outcomes of one evaluation. Framework-free.

Deliberately imports no agent framework. The evaluation's inputs, its two possible outcomes,
and their validation are the reviewable part of this layer, and they must stay testable in an
environment that has the numeric core but no graph library — the same split, and the same
reason, as `interactions/tool.py` against `interactions/langgraph_tool.py`.

THE CARE PLAN CARRIES THE BOUNDS AND THIS MODULE SUPPLIES NO DEFAULT FOR THEM. A therapeutic
range is a clinical decision about one patient, written by their own clinician; a default in
code would be this software choosing a range and then judging a patient against it. Every
constructor here therefore fails closed on a missing or malformed bound rather than filling
one in.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from typing import Final

from agent_pk.pk.model import DoseEvent, Observation, PkInputError
from agent_pk.pk.priors import Covariates

#: Simulated futures a sampling offer is averaged over, unless a case says otherwise. This is
#: the value every committed demonstration figure was produced at.
DEFAULT_OFFER_SIMULATIONS: Final[int] = 24


def _require_finite(value: float, name: str) -> None:
    """Raise unless `value` is a real, finite number.

    `bool` is rejected by type before anything else: `bool` subclasses `int`, so every later
    test passes for `True` and a boolean silently becomes 1.0.

    Args:
        value: The candidate.
        name: Field name, for the message.

    Raises:
        PkInputError: If the value is a bool, not a real number, or not finite.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PkInputError(f"{name} must be a real number, got {type(value).__name__}")
    if not math.isfinite(float(value)):
        raise PkInputError(f"{name} must be finite, got {value!r}")


def _require_int(value: int, name: str) -> None:
    """Raise unless `value` is a genuine int. Rejects `bool` first, for the reason above.

    Args:
        value: The candidate.
        name: Field name, for the message.

    Raises:
        PkInputError: If the value is a bool or not an int.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise PkInputError(f"{name} must be an int, got {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class CarePlan:
    """The clinician-authored plan an evaluation is judged against.

    Attributes:
        lower_bound_ng_per_ml: The plan's lower therapeutic boundary, on the measured scale a
            laboratory reports. REQUIRED — no default, see the module docstring.
        upper_bound_ng_per_ml: The plan's upper therapeutic boundary. REQUIRED.
        plan_text_from_clinician: Text this patient's own clinician wrote for them. Carried
            verbatim into the patient channel, where it is the clinician's own finding about
            their own patient rather than the software speaking — which is the distinction
            360j(o)(1)(D) turns on. The software never authors it and never edits it.
        band_citation: Where the range came from. A range shown without its source cannot be
            reviewed, and criterion 4 makes the reliability of the driving evidence part of
            what must be reviewable.
    """

    lower_bound_ng_per_ml: float
    upper_bound_ng_per_ml: float
    plan_text_from_clinician: str
    band_citation: str

    def __post_init__(self) -> None:
        _require_finite(self.lower_bound_ng_per_ml, "lower_bound_ng_per_ml")
        _require_finite(self.upper_bound_ng_per_ml, "upper_bound_ng_per_ml")
        if self.lower_bound_ng_per_ml <= 0.0:
            raise PkInputError("lower_bound_ng_per_ml must be > 0")
        if self.upper_bound_ng_per_ml <= self.lower_bound_ng_per_ml:
            raise PkInputError(
                "upper_bound_ng_per_ml must exceed lower_bound_ng_per_ml"
            )
        if not self.plan_text_from_clinician.strip():
            raise PkInputError(
                "plan_text_from_clinician must not be empty — the patient channel has no "
                "prose of its own to fall back on, and an empty plan would silently remove "
                "the only clinician-authored text the patient sees"
            )
        if not self.band_citation.strip():
            raise PkInputError("band_citation must not be empty")


@dataclass(frozen=True, slots=True)
class PatientCase:
    """Everything one evaluation runs on. Synthetic only — see the PY-PROFILE data contract.

    Times are hours since this patient's own reference instant, never wall-clock datetimes.
    The reference instant belongs to the presentation layer; carrying it here would put
    timezone handling inside the decision path.

    Attributes:
        covariates: The patient's covariates, which shift the population prior.
        doses: The dosing history, INCLUDING any dose scheduled between now and the target.
            A prediction whose history stops short of the next dose is a prediction of the
            previous dose's tail, which is the defect that made a whole demo read backwards.
        troughs: Measured pre-dose trough concentrations. Held SEPARATELY from post-dose
            curve samples rather than inferred from the timings, because inferring it needs a
            rule about how close to a dose counts as "pre-dose" — and the obvious rule, an
            exact match on the dose time, silently returns nothing: a real trough is drawn a
            few minutes BEFORE the dose, so exact equality never fires and variability would
            report as unavailable on a patient who has four of them. The distinction is
            clinical, the source data already carries it, so it is a field.
        curve_samples: Post-dose samples from a sampling occasion. These identify absorption;
            troughs do not. Mixing them into the trough series would report a variability the
            patient does not have, since a sample an hour after a dose is near the peak.
        plan: The care plan this evaluation is judged against.
        target_time_h: When the trough being predicted falls.
        next_dose_time_h: The dose any proposed extra samples would be timed from.
        prediction_seed: Explicit seed for the prediction sampler.
        offer_seed: Explicit seed for the sampling-offer simulation. Separate from
            `prediction_seed` so that re-running one does not silently move the other.
        offer_simulations: How many simulated futures the sampling offer averages over. A
            TUNING parameter, carried on the case rather than buried in the evaluation so that
            a run states what it was measured at — a forecast averaged over four futures and
            one averaged over twenty-four are not the same claim, and a caller that lowers it
            for speed should have to say so where the rest of the run's settings are. The
            default is the value the demonstration and the committed figures use.
    """

    covariates: Covariates
    doses: tuple[DoseEvent, ...]
    troughs: tuple[Observation, ...]
    curve_samples: tuple[Observation, ...]
    plan: CarePlan
    target_time_h: float
    next_dose_time_h: float
    prediction_seed: int
    offer_seed: int
    offer_simulations: int = DEFAULT_OFFER_SIMULATIONS

    def __post_init__(self) -> None:
        if not self.doses:
            raise PkInputError(
                "doses must not be empty — there is nothing to predict from, and an empty "
                "history would otherwise be fitted as a patient on no treatment"
            )
        _require_finite(self.target_time_h, "target_time_h")
        _require_finite(self.next_dose_time_h, "next_dose_time_h")
        _require_int(self.prediction_seed, "prediction_seed")
        _require_int(self.offer_seed, "offer_seed")
        _require_int(self.offer_simulations, "offer_simulations")
        if self.offer_simulations < 1:
            raise PkInputError("offer_simulations must be >= 1")
        times = [obs.time_h for obs in self.troughs + self.curve_samples]
        if len(set(times)) != len(times):
            raise PkInputError(
                "two observations share a time. One instant cannot hold two different "
                "concentrations, and the fitter would weight the record as though it did"
            )

    @property
    def observations(self) -> tuple[Observation, ...]:
        """Every measured concentration, in time order. What the fitter is given.

        Assembled from the two declared groups rather than stored, so the union can never
        disagree with its parts.
        """
        merged = self.troughs + self.curve_samples
        return tuple(sorted(merged, key=lambda obs: obs.time_h))


@dataclass(frozen=True, slots=True)
class ReviewRequired:
    """The outcome when no `ClinicianView` could be built, carrying why.

    THIS TYPE EXISTS SO THAT A FAILURE CANNOT BE READ AS AN ABSENT ESCALATION. When the
    predictive sampler degenerates, the honest statement is "this could not be evaluated",
    and the dangerous statement is `NO_ACTION` — which is what a caller that swallowed the
    exception would produce, and which is indistinguishable on screen from a patient who is
    comfortably in range. `predict_trough`'s own docstring requires the caller to route the
    degenerate case to a human; a distinct return type is how that requirement is carried
    rather than remembered.

    Attributes:
        stage: Which step could not complete — "fit", "prediction" or "view".
        reason: Plain English, written to be shown to a clinician rather than logged.
    """

    stage: str
    reason: str

    def __post_init__(self) -> None:
        if self.stage not in ("fit", "prediction", "view"):
            raise PkInputError(f"unknown stage {self.stage!r}")
        if not self.reason.strip():
            raise PkInputError("reason must not be empty")
