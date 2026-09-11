"""priors.py — the published population prior for once-daily extended-release tacrolimus.

EVERY parameter in this module is a point estimate from ONE named published model:

    Fernández-Alarcón B, et al. Guiding the starting dose of the once-daily formulation of
    tacrolimus in "de novo" adult renal transplant patients: a population approach.
    Frontiers in Pharmacology 2024;15:1456565. doi:10.3389/fphar.2024.1456565

    Two-compartment model, delayed first-order absorption, linear elimination.
    n = 138 de novo adult renal transplant recipients on extended-release tacrolimus
    (29 with full 24-hour profiles on day 5; 109 with troughs on days 5, 10 and 15).

**Why that sentence is the point of this file.** An earlier revision carried plausible-looking
values that were not taken from any published model — they were shaped like the covariates
population models retain, at magnitudes that looked reasonable. A quantitative claim resting on
those is not a finding, it is a simulation of one. The structural claims (shrinkage biases an
atypical patient toward the prior) survive any prior; the MAGNITUDES did not survive contact
with real estimates. The residual error is the clearest case: it was carried at 18% where this
model measured 28.2%, so every interval the product showed was about a third too narrow, in the
direction that flatters us.

**THE POPULATION LIMIT, which must travel with the numbers.** This is a DE NOVO model, fitted on
days 5-15 after transplantation. Agent PK's maintenance patient is months out, where clearance
and its covariates have moved. Applying it there is an extrapolation of exactly the same kind as
applying the limited-sampling equation outside its Japanese cohort, and the clinician view must
say so where the numbers appear. It is the best-matched published model for the formulation and
the organ; it is not a maintenance model.

**WHAT THIS MODULE DOES NOT TAKE FROM THE SOURCE, declared rather than silently diverged:**

1. *Haematocrit.* NO LONGER A DIVERGENCE — IMPLEMENTED 2026-09-09. This item previously said the
   standardisation was not implemented "because we do not have its exact transformation", and
   that haematocrit was therefore inert. Both halves were wrong. The transformation is published
   and simple, and leaving it out was not neutral: the source's parameters describe
   HAEMATOCRIT-STANDARDISED concentrations, so feeding raw whole-blood values to a prior fitted
   on standardised ones mis-specifies the fit for any patient away from 45%. See
   `standardise_to_reference_haematocrit`, `HAEMATOCRIT_STANDARDISATION_SOURCE` for the formula
   and its first outcome evidence (July 2026), and `HAEMATOCRIT_EVIDENCE_LIMITS` for how far
   that evidence reaches. **This build does not assume anaemia**: the demo patient sits at the
   reference haematocrit where the correction is the identity, so it is a capability for real
   use rather than something the demo leans on.
2. *Absorption.* `ka` is FIXED at 2.0/h in the source, because their data could not identify it.
   Any fit here that ESTIMATES absorption is going beyond the source model, and the prior SD it
   uses (`OMEGA_LOG_KA`) is OURS, not theirs. It is labelled at the constant.
3. *Volume allometry.* NOT A DIVERGENCE — WITHDRAWN 2026-09-09. This item previously claimed
   the exponent on Vc/F was OURS because the source was silent on it. The source is NOT silent:
   it states "allometric exponents were fixed to 0.75 for flow pharmacokinetic parameters and to
   1 for central compartment distribution volume". The value used here always matched; the claim
   that we had chosen it did not. Recorded rather than deleted because the error ran the wrong
   way — the module was UNDERSTATING its own sourcing, in a file whose entire point is that every
   number is traceable, and an unnecessary "ours" is as much a provenance defect as a missing
   citation.
4. *Age above 60.* The source reduces clearance by 0.0562 L/h per year in patients over 60. Our
   reading of whether that multiplies age or years-above-60 is not certain, so it is applied as
   years ABOVE 60 (the reading the paper's prose supports) and age defaults to None, in which
   case no age term applies at all. A patient of 60 or under is unaffected either way.

An UNKNOWN covariate widens the prior rather than being guessed. That is the design rule of this
module: missing information makes the answer less certain, never differently certain.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, get_args

from agent_pk.pk.model import (
    PkInputError,
    PkParameters,
    _require_finite,
    _require_positive_finite,
)

Formulation = Literal["advagraf_prolonged_release"]
"""Which tacrolimus product the patient takes. ONE product, named explicitly.

ADVAGRAF (Astellas) PROLONGED-RELEASE ONLY — the formulation the source model was fitted in.

RENAMED FROM `once_daily_er` 2026-09-09, and the rename is the fix rather than cosmetic. There is
more than one once-daily tacrolimus, and they are NOT interchangeable: LCPT (MeltDose, marketed as
Envarsus XR) has materially higher bioavailability and a later Tmax than Advagraf, which is why it
carries its own conversion ratio and its own trough targets. A label reading `once_daily_er`
admitted both and distinguished neither, and under it the project reached the point of pairing
THIS model's parameters with a therapeutic range quoted from an LCPT trial. Naming the product
makes that mistake unrepresentable instead of merely unlikely.

There is no immediate-release model here and no LCPT model here, so there is no prior for either —
a caller asking for one gets a refusal rather than Advagraf parameters wearing another product's
label. An earlier revision also offered `twice_daily_ir` and supplied it with an absorption
constant nobody had published for it; that branch was REMOVED, not deprecated."""


# ── The published model's point estimates (Table 4) ──────────────────────────

SOURCE_CITATION = (
    "Fernandez-Alarcon B, et al. Guiding the starting dose of the once-daily formulation of "
    "tacrolimus in de novo adult renal transplant patients: a population approach. "
    "Front Pharmacol 2024;15:1456565. doi:10.3389/fphar.2024.1456565"
)

SOURCE_URL = "https://doi.org/10.3389/fphar.2024.1456565"
"""Resolver URL for the DOI named in SOURCE_CITATION.

Kept HERE rather than in the consumer that needs it, because this module owns the source's
identity: a citation and its locator are one fact, and a second module holding its own copy of
the URL is how the two drift apart. `EvidenceNote` requires a non-empty `source_url`, so every
clinician-facing citation of the population model reads this constant."""

SOURCE_POPULATION_LIMIT = (
    "Derived in 138 DE NOVO adult renal transplant recipients on extended-release tacrolimus, "
    "sampled on days 5 to 15 after transplantation. A maintenance patient months post-transplant "
    "is an extrapolation."
)

CL_F_CARRIER_L_PER_H_70KG = 26.5
"""theta_1 — CL/F for a CYP3A5 *1 CARRIER at 70 kg, aged 60 or under. L/h. RSE 7.8%.

Note the reference group: the source parameterises on CARRIERS (expressers), where an earlier
revision of this module used non-expressers as its reference. The direction of the genotype
effect is unchanged; which group carries the base value is not."""

CYP3A5_NON_CARRIER_FACTOR = 0.666
"""theta_2 — multiplicative effect on CL/F for CYP3A5 *1 NON-carriers. RSE 8.1%.

So carriers clear about 1/0.666 = 1.50x faster than non-carriers."""

AGE_EFFECT_L_PER_H_PER_YEAR = 0.0562
"""theta_3 — reduction in CL/F per year above 60. L/h/70kg/year. RSE 26.0%.

See the module docstring, item 4: applied as years ABOVE 60, and inert when age is unknown."""

VC_F_L_70KG = 327.0
"""theta_4 — apparent central volume at 70 kg. L. RSE 14.0%."""

VP_F_L = 298.0
"""Apparent peripheral volume. L. RSE 17.4%. NOT weight-scaled, per the source."""

CLD_F_L_PER_H_70KG = 51.9
"""Apparent intercompartmental (distribution) clearance at 70 kg. L/h. RSE 27.0%."""

KA_PER_H = 2.0
"""Absorption rate constant. Per hour. FIXED in the source model, not estimated.

The source fixed it "based on a range of physiologically meaningful assayed values" because its
data — mostly troughs — could not identify absorption. Anything here that estimates it is an
extension beyond the source; see OMEGA_LOG_KA."""

LAG_H = 0.341
"""Absorption lag time (ALAG1). Hours. RSE 9.4%."""

BSV_CLEARANCE_CV = 0.321
"""Between-patient variability on CL/F, as a coefficient of variation. RSE 15.1%."""

BSV_VOLUME_CV = 0.482
"""Between-patient variability on Vc/F, as a coefficient of variation. RSE 75.4%.

That RSE is large enough to be worth saying out loud: the source's own estimate of this
variability is imprecise."""

PROPORTIONAL_RESIDUAL_CV = 0.282
"""Residual (unexplained) error, proportional model, as a CV. RSE 3.8%.

The source tested combined and additive models and found neither superior."""

ALLOMETRIC_EXPONENT_CLEARANCE = 0.75
"""Weight exponent on CL/F and CLD/F, per the source."""

ALLOMETRIC_EXPONENT_VOLUME = 1.0
"""Weight exponent on Vc/F. PUBLISHED, not ours.

The source states it directly: "allometric exponents were fixed to 0.75 for flow pharmacokinetic
parameters and to 1 for central compartment distribution volume". An earlier revision of this
docstring claimed the value was OURS because the source was silent. It is not silent, and the
claim was withdrawn on 2026-09-09 — see module docstring item 3. Corrected in BOTH places: the
first pass fixed only the module docstring and left this line still asserting the withdrawn
claim, which is the same "the claim outlives the file you edited" pattern this module has now
been bitten by twice."""

AGE_THRESHOLD_YEARS = 60.0
"""Age above which the source applies a clearance reduction."""


# ── Derived from the published estimates ─────────────────────────────────────


def _omega_from_cv(cv: float) -> float:
    """Log-scale SD corresponding to a coefficient of variation, under a log-normal.

    The source models between-patient variability with an exponential error model, i.e.
    log-normal individual parameters, and reports the variability as a %CV. The log-scale SD
    that produces that CV is `sqrt(ln(1 + CV**2))`. Converting rather than using the CV directly
    matters at these magnitudes: at CV 0.482 the two differ by about 5%.

    Args:
        cv: Coefficient of variation, as a fraction.

    Returns:
        The corresponding SD on the log scale.
    """
    return math.sqrt(math.log(1.0 + cv * cv))


REFERENCE_WEIGHT_KG = 70.0
"""The weight the source's parameters are normalised to."""

REFERENCE_CLEARANCE_L_PER_H = CL_F_CARRIER_L_PER_H_70KG * CYP3A5_NON_CARRIER_FACTOR
"""CL/F for a CYP3A5 NON-carrier at the reference weight, aged 60 or under. L/h.

Derived from the two published thetas rather than typed as its own number, so it cannot drift
away from them."""

CYP3A5_EXPRESSER_CLEARANCE_FACTOR = 1.0 / CYP3A5_NON_CARRIER_FACTOR
"""How much faster a CYP3A5 expresser clears, relative to a non-expresser. About 1.50."""

OMEGA_LOG_CLEARANCE = _omega_from_cv(BSV_CLEARANCE_CV)
OMEGA_LOG_VOLUME = _omega_from_cv(BSV_VOLUME_CV)

OMEGA_LOG_KA = 0.60
"""Prior SD of log(ka). OURS, NOT THE SOURCE'S — the source FIXED ka and therefore published no
variability for it.

Deliberately wide, roughly a three-fold range at one SD, so that a patient's own post-dose points
rather than this number determine an estimated absorption rate. It is the one prior width in this
module that is not published, and a fit that estimates absorption is resting on it."""

CYP3A5_EXPRESSER_PREVALENCE_DEFAULT = 0.30
"""Probability that an untested patient is a CYP3A5 expresser.

OURS, AND POPULATION-DEPENDENT — expresser prevalence differs substantially between ancestries
and this default matches no single population. It is a field on Covariates precisely so that it
is set deliberately by the serving centre rather than inherited from this line."""

REFERENCE_HAEMATOCRIT = 0.45
"""The haematocrit observed concentrations are standardised to, as a fraction.

The source standardises whole-blood tacrolimus to this value BEFORE modelling — the step reduced
its objective function by 37.7 units — so every parameter in this module describes a
STANDARDISED concentration. See `standardise_to_reference_haematocrit`."""

HAEMATOCRIT_STANDARDISATION_SOURCE = (
    "Hct-adjusted Tac = (0.45 / Hct) x measured Tac. Mechanism: tacrolimus partitions heavily "
    "into erythrocytes (blood-to-plasma ratio ~50 at Hct 0.45), so a low haematocrit lowers the "
    "whole-blood concentration for the same amount of drug in the body and reads as increased "
    "clearance. OUTCOME EVIDENCE, as of July 2026: Vancouver General Hospital single-centre "
    "retrospective cohort, 344 adult LIVER transplant recipients (2018-2022), Front Transplant "
    "2026, doi:10.3389/frtra.2026.1878595, published 3 July 2026. Each 1 ng/mL of delta-Tac (the "
    "gap between Hct-adjusted and measured concentration) carried a 15% higher hazard of acute "
    "kidney injury (HR 1.15, 95% CI 1.08-1.24, p<0.001), with AKI in 69.8% of the cohort within "
    "90 days. There was NO association with T-cell-mediated rejection (HR 0.93, 95% CI "
    "0.77-1.14, p=0.50)."
)
"""The formula, its mechanism, and the first outcome evidence for it — carried as one string so a
number can never be shown without the study and its limits travelling beside it."""

HAEMATOCRIT_EVIDENCE_LIMITS = (
    "INDICATIVE, NOT ESTABLISHED — and the distinction is the point rather than a hedge. The "
    "correction is mechanistically sound and pharmacokinetically validated; what is NOT yet done "
    "is prospective, multi-centre validation against patient OUTCOMES. The July 2026 cohort is "
    "single-centre, retrospective, and in LIVER rather than kidney recipients. Its authors state "
    "the limits themselves: residual confounding they could not adjust away; delta-Tac is "
    "derived in part FROM haematocrit, so it may partly track anaemia and illness severity "
    "rather than drug exposure; it is a standardisation rather than a direct measurement of "
    "unbound drug; and the study 'does not evaluate a hematocrit-adjusted dosing strategy', so "
    "it cannot establish causality. They write that the findings 'warrant evaluation in "
    "independent cohorts' and that 'replication studies are currently underway'. Read the "
    "association as a good hypothesis with its first supporting evidence, not as proof that "
    "adjusting improves outcomes."
)
"""Why a mechanistically-correct adjustment is still not a proven clinical benefit.

This is the ordinary shape of evidence in medicine and it is worth stating plainly for a reader
who is not a scientist: a correction can be right about the CHEMISTRY and still not be shown to
change what happens to patients. Establishing that takes studies designed for the question -
ideally prospective, across multiple centres, comparing the adjusted strategy against the current
one - because a single retrospective centre cannot separate the adjustment's effect from
everything else that differs between sicker and healthier patients. We adopt the correction
because the mechanism and the pharmacokinetics support it, and we say exactly how far the outcome
evidence has got, which as of July 2026 is one cohort in a different organ."""

ANAEMIA_HAEMATOCRIT_THRESHOLD = 0.36
"""Below this haematocrit the standardisation moves a concentration by more than ~25%.

A THRESHOLD FOR DISCLOSURE, not a diagnosis: it marks where the correction stops being a
rounding detail and starts materially changing what the model is told. It sits near the
conventional lower limits of normal haematocrit for adults, which is why a patient below it is
also likely to be clinically anaemic — but this constant exists to decide when the clinician must
be TOLD the adjustment is doing real work, not to label anyone."""

_MIN_HAEMATOCRIT = 0.10
_MAX_HAEMATOCRIT = 0.70
_MIN_AGE_YEARS = 0.0
_MAX_AGE_YEARS = 120.0


def standardise_to_reference_haematocrit(
    concentration_ng_per_ml: float, haematocrit: float
) -> float:
    """Convert a MEASURED whole-blood concentration to the haematocrit-standardised scale.

        standardised = (0.45 / haematocrit) * measured

    Every parameter in this module describes a STANDARDISED concentration, because the source
    applied exactly this step before fitting. So a raw laboratory value must be put on that scale
    before it is compared with anything here, and a prediction must be put BACK on the measured
    scale before it is compared with a therapeutic range or shown to a clinician
    (`express_as_measured`).

    WHY IT MATTERS, in one sentence a clinician would recognise: tacrolimus sits mostly inside red
    cells, so an anaemic patient's whole-blood level is low for the same amount of drug in the
    body, and a model that is not told about the anaemia reads that as fast clearance and predicts
    a lower trough than the patient will actually have.

    Args:
        concentration_ng_per_ml: The measured whole-blood concentration.
        haematocrit: The patient's haematocrit as a FRACTION (0.45, never 45).

    Returns:
        The concentration on the standardised scale, in ng/mL.

    Raises:
        PkInputError: If either argument is a bool, non-finite, or out of physical range.
    """
    _require_positive_finite(concentration_ng_per_ml, "concentration_ng_per_ml")
    _require_positive_finite(haematocrit, "haematocrit")
    if not _MIN_HAEMATOCRIT <= haematocrit <= _MAX_HAEMATOCRIT:
        raise PkInputError(
            f"haematocrit must be a fraction in [{_MIN_HAEMATOCRIT}, {_MAX_HAEMATOCRIT}], "
            f"got {haematocrit!r} — pass 0.45, not 45"
        )
    return concentration_ng_per_ml * (REFERENCE_HAEMATOCRIT / haematocrit)


def express_as_measured(standardised_ng_per_ml: float, haematocrit: float) -> float:
    """Convert a standardised concentration back to the scale a laboratory reports.

    The exact inverse of `standardise_to_reference_haematocrit`. Required because the therapeutic
    range, the escalation boundaries and everything shown to a clinician are defined on a MEASURED
    trough — so a prediction made in standardised space has to come back before it means anything.
    Omitting this direction would be the same class of error as omitting the standardisation, and
    it would run the opposite way.

    Args:
        standardised_ng_per_ml: A concentration on the haematocrit-standardised scale.
        haematocrit: The patient's haematocrit as a FRACTION.

    Returns:
        The concentration on the measured whole-blood scale, in ng/mL.

    Raises:
        PkInputError: If either argument is a bool, non-finite, or out of physical range.
    """
    _require_positive_finite(standardised_ng_per_ml, "standardised_ng_per_ml")
    _require_positive_finite(haematocrit, "haematocrit")
    if not _MIN_HAEMATOCRIT <= haematocrit <= _MAX_HAEMATOCRIT:
        raise PkInputError(
            f"haematocrit must be a fraction in [{_MIN_HAEMATOCRIT}, {_MAX_HAEMATOCRIT}], "
            f"got {haematocrit!r} — pass 0.45, not 45"
        )
    return standardised_ng_per_ml * (haematocrit / REFERENCE_HAEMATOCRIT)


@dataclass(frozen=True, slots=True)
class Covariates:
    """Patient covariates that shift the population prior.

    Attributes:
        weight_kg: Body weight. Scales CL/F, Vc/F and CLD/F.
        haematocrit: Fraction, not percent — 0.45, never 45. **None means NOT MEASURED**, and
            that is the default. It is deliberately NOT defaulted to the reference value: doing
            so silently asserts the patient is not anaemic, which is a guess about a covariate
            that shifts the answer in the unsafe direction — an unmeasured anaemia makes the
            model read fast clearance and UNDERSTATE the probability of a sub-therapeutic
            trough. An unknown quantity must be carried as unknown, not filled in. When it is
            None the standardisation is the identity and `PopulationPrior.haematocrit_known` is
            False so the clinician view can say so; when a value is given the correction does
            real work. See `standardise_to_reference_haematocrit` and
            `HAEMATOCRIT_EVIDENCE_LIMITS`.
        age_years: Age. Reduces clearance only above 60, per the source. None means unknown, in
            which case no age adjustment is applied at all.
        cyp3a5_expresser: True, False, or None when the genotype has not been tested.
        expresser_prevalence: Probability of being an expresser, used only when the genotype is
            unknown. Population-dependent; see the constant's docstring.
        formulation: Advagraf prolonged-release only. Named rather than generic — see Formulation.

    NOT PRESENT, DELIBERATELY: days since transplant. The source is a de novo model with
    time-varying covariates and this module does not implement them, so a field for it would be
    a false contract — a caller could set it and believe the prior had been adjusted.
    """

    weight_kg: float = REFERENCE_WEIGHT_KG
    haematocrit: float | None = None
    age_years: float | None = None
    cyp3a5_expresser: bool | None = None
    expresser_prevalence: float = CYP3A5_EXPRESSER_PREVALENCE_DEFAULT
    formulation: Formulation = "advagraf_prolonged_release"

    def __post_init__(self) -> None:
        if self.formulation not in get_args(Formulation):
            raise PkInputError(
                f"formulation must be one of {get_args(Formulation)}, "
                f"got {self.formulation!r} — this module carries ONE published model, for Advagraf "
                f"prolonged-release: there is no published immediate-release model here, and "
                f"no LCPT/Envarsus prior either"
            )
        _require_positive_finite(self.weight_kg, "weight_kg")
        if self.haematocrit is None:
            pass  # not measured — carried as unknown rather than filled in
        else:
            _require_positive_finite(self.haematocrit, "haematocrit")
        if self.haematocrit is not None and not (
            _MIN_HAEMATOCRIT <= self.haematocrit <= _MAX_HAEMATOCRIT
        ):
            raise PkInputError(
                f"haematocrit must be a fraction in "
                f"[{_MIN_HAEMATOCRIT}, {_MAX_HAEMATOCRIT}], got {self.haematocrit!r} "
                f"— pass 0.45, not 45"
            )
        if self.age_years is not None:
            _require_positive_finite(self.age_years, "age_years")
            if not _MIN_AGE_YEARS < self.age_years <= _MAX_AGE_YEARS:
                raise PkInputError(
                    f"age_years must be in ({_MIN_AGE_YEARS}, {_MAX_AGE_YEARS}], "
                    f"got {self.age_years!r}"
                )
        if self.cyp3a5_expresser is not None and not isinstance(
            self.cyp3a5_expresser, bool
        ):
            raise PkInputError("cyp3a5_expresser must be True, False or None")
        _require_finite(self.expresser_prevalence, "expresser_prevalence")
        if not 0.0 <= self.expresser_prevalence <= 1.0:
            raise PkInputError(
                f"expresser_prevalence must be a probability in [0, 1], "
                f"got {self.expresser_prevalence!r}"
            )


@dataclass(frozen=True, slots=True)
class PopulationPrior:
    """A covariate-adjusted prior on the log-scale PK parameters.

    Attributes:
        log_clearance_mean: Prior mean of log(CL/F).
        log_volume_mean: Prior mean of log(Vc/F).
        omega_log_clearance: Prior SD of log(CL/F).
        omega_log_volume: Prior SD of log(Vc/F).
        volume_peripheral_l: Vp/F, held at the published value. Not fitted — the source
            reports no between-patient variability for it.
        intercompartmental_clearance_l_per_h: CLD/F, weight-scaled, held at the published value.
        ka_per_h: Absorption rate constant. Fixed at the published value unless a fit estimates
            it, in which case this is the prior mean.
        lag_h: Absorption lag, held at the published value.
        proportional_residual_cv: Residual error CV used by the fitter.
        haematocrit: The haematocrit used for the standardisation. Carried on the PRIOR rather
            than passed separately for the same reason `residual_cv` is carried on the fit: a
            caller cannot then pair a patient with someone else's haematocrit. REQUIRED — it has
            no default, because the value that would be defaulted is precisely the guess this
            design refuses to make silently.
        haematocrit_known: False when the patient's haematocrit was NOT measured, in which case
            `haematocrit` holds the reference value and the correction is the identity. This flag
            is the disclosure: an unmeasured anaemia biases the fit toward fast clearance and
            UNDERSTATES the probability of a sub-therapeutic trough, so a clinician reading the
            output needs to know the correction did not run. Mirrors `genotype_known`.
        genotype_known: False when the clearance prior was widened for unknown CYP3A5 status.
        omega_log_ka: Prior SD of log(ka). OURS, not the source's — see OMEGA_LOG_KA.
        formulation: Which product this prior was built for.
    """

    log_clearance_mean: float
    log_volume_mean: float
    omega_log_clearance: float
    omega_log_volume: float
    volume_peripheral_l: float
    intercompartmental_clearance_l_per_h: float
    ka_per_h: float
    lag_h: float
    proportional_residual_cv: float
    genotype_known: bool
    haematocrit: float
    haematocrit_known: bool
    omega_log_ka: float = OMEGA_LOG_KA
    formulation: Formulation = "advagraf_prolonged_release"

    @property
    def log_ka_mean(self) -> float:
        """Prior mean of log(ka), for the three-parameter fit."""
        return math.log(self.ka_per_h)

    def individual(
        self,
        clearance_l_per_h: float,
        volume_central_l: float,
        ka_per_h: float | None = None,
    ) -> PkParameters:
        """Build individual parameters, filling in everything this model holds FIXED.

        The fit estimates CL/F and Vc/F, because those are the only two the source model gives
        between-patient variability for. Vp/F, CLD/F and the lag come from the prior unchanged.
        Routed through one method so a caller cannot assemble a `PkParameters` that silently
        disagrees with the prior it was fitted against — five call sites previously built it by
        hand, and five hand-built copies of a contract is four too many.

        Args:
            clearance_l_per_h: The individual CL/F.
            volume_central_l: The individual Vc/F.
            ka_per_h: The individual absorption rate. None uses the prior's fixed value, which
                is the source model's behaviour.

        Returns:
            Individual parameters ready for `concentration_at`.
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


def prior_for(covariates: Covariates) -> PopulationPrior:
    """Build the covariate-adjusted population prior for one patient.

    Implements the source's clearance equation:

        CL/F = [26.5 * 0.666**non_carrier - 0.0562 * years_above_60] * (weight/70)**0.75

    Args:
        covariates: The patient's covariates. Unknown genotype widens AND shifts the clearance
            prior; unknown age applies no age term.

    Returns:
        A PopulationPrior on the log scale.

    Raises:
        PkInputError: If the covariates imply a non-positive clearance, which the age term can
            do for an implausibly old patient. Raised rather than clamped, because a clamped
            clearance is an invented one.
    """
    clearance = REFERENCE_CLEARANCE_L_PER_H
    genotype_known = covariates.cyp3a5_expresser is not None
    log_factor = math.log(CYP3A5_EXPRESSER_CLEARANCE_FACTOR)

    if covariates.cyp3a5_expresser is True:
        clearance *= CYP3A5_EXPRESSER_CLEARANCE_FACTOR
        omega_clearance = OMEGA_LOG_CLEARANCE
    elif covariates.cyp3a5_expresser is False:
        omega_clearance = OMEGA_LOG_CLEARANCE
    else:
        # Unknown genotype is a MIXTURE, not the non-expresser case.
        #
        # Widening omega alone leaves the prior MEAN at the non-expresser value, which biases a
        # true expresser's predicted concentration UPWARD by the full factor — so a genuinely
        # sub-therapeutic patient can sit below the plan's lower bound while the interval's lower
        # quantile stays above it, and the escalation never fires. That is the exact failure this
        # product exists to prevent, and it is most likely in populations where expressers are
        # common. Both moments of the mixture are therefore carried.
        prevalence = covariates.expresser_prevalence
        # ARITHMETIC mixture on the natural scale, not exp(p * log(factor)). The geometric form
        # is the smaller of the two by AM-GM, so it UNDERSTATES clearance and therefore
        # OVERSTATES predicted concentration — biasing in the one direction that makes
        # crosses_below harder to fire for a genuinely sub-therapeutic expresser.
        clearance *= (1.0 - prevalence) + prevalence * CYP3A5_EXPRESSER_CLEARANCE_FACTOR
        mixture_variance = prevalence * (1.0 - prevalence) * log_factor**2
        omega_clearance = max(
            math.sqrt(OMEGA_LOG_CLEARANCE**2 + mixture_variance), OMEGA_LOG_CLEARANCE
        )

    # The age term is SUBTRACTED before allometric scaling, per the source's equation, and only
    # above the threshold. Unknown age contributes nothing rather than a guessed value.
    if covariates.age_years is not None and covariates.age_years > AGE_THRESHOLD_YEARS:
        clearance -= AGE_EFFECT_L_PER_H_PER_YEAR * (
            covariates.age_years - AGE_THRESHOLD_YEARS
        )

    weight_ratio = covariates.weight_kg / REFERENCE_WEIGHT_KG
    clearance *= weight_ratio**ALLOMETRIC_EXPONENT_CLEARANCE

    if not math.isfinite(clearance) or clearance <= 0.0:
        raise PkInputError(
            f"covariates imply a non-positive clearance ({clearance!r}); the age term cannot "
            "be applied to this patient without inventing a floor"
        )

    volume = VC_F_L_70KG * weight_ratio**ALLOMETRIC_EXPONENT_VOLUME
    distribution_clearance = (
        CLD_F_L_PER_H_70KG * weight_ratio**ALLOMETRIC_EXPONENT_CLEARANCE
    )

    return PopulationPrior(
        log_clearance_mean=math.log(clearance),
        log_volume_mean=math.log(volume),
        omega_log_clearance=omega_clearance,
        omega_log_volume=OMEGA_LOG_VOLUME,
        # Vp/F is NOT weight-scaled, per the source.
        volume_peripheral_l=VP_F_L,
        intercompartmental_clearance_l_per_h=distribution_clearance,
        ka_per_h=KA_PER_H,
        lag_h=LAG_H,
        proportional_residual_cv=PROPORTIONAL_RESIDUAL_CV,
        genotype_known=genotype_known,
        haematocrit=(
            REFERENCE_HAEMATOCRIT
            if covariates.haematocrit is None
            else covariates.haematocrit
        ),
        haematocrit_known=covariates.haematocrit is not None,
        omega_log_ka=OMEGA_LOG_KA,
        formulation=covariates.formulation,
    )
