# Model card — Agent PK tacrolimus exposure model

**One page, and structured deliberately.** The nine headings below are the source-attribute
categories ONC's HTI-1 final rule requires of a Predictive Decision Support Intervention in
certified health IT (45 CFR 170.315(b)(11)). Agent PK is not certified health IT and is not
directly bound by that criterion — but HTI-1's own definition of a Predictive DSI is *"technology
that supports decision-making based on algorithms or models that derive relationships from
training data and then produce an output that results in prediction, classification,
recommendation, evaluation, or analysis"*, which describes this product exactly. Writing the card
to that shape means it drops into a certified environment instead of being re-done for one.

| | |
|---|---|
| **Name / version** | Agent PK tacrolimus PK core, 0.1.0 |
| **Date** | 2026-09-08 |
| **Status** | Research prototype. **Not a medical device. Not cleared or approved by any regulator. Not for use in the care of a real patient.** |

---

### 1. Details and output of the intervention

The published two-compartment, delayed-first-order-absorption population model of Fernández-Alarcón et al., *Front Pharmacol* 2024;15:1456565, fitted per patient by
MAP-Bayesian estimation of apparent clearance (CL/F), apparent volume (V/F) and — only when
post-dose samples can identify it — the absorption rate (ka).

**Output:** a predicted whole-blood tacrolimus concentration **interval** at a future time, a
verdict on whether that interval crosses a boundary a clinician wrote into the care plan, an
estimated 24-hour exposure with its credible interval, and an attribution of what is driving a
change. Never a dose, and never a bare point estimate.

### 2. Purpose of the intervention

To tell a clinician **when to look** at a transplant patient's tacrolimus level, in the weeks
between scheduled blood draws. It is a triage and monitoring-scheduling aid. It does not
diagnose, does not adjust therapy, and does not replace a blood draw.

**Intended user:** a transplant clinician. The patient-facing channel displays the patient's own
data and their own clinician's own instructions and interprets nothing (see `GUARDRAILS.md`).

### 3. Cautioned out-of-scope use

- **Any real patient.** This is a prototype on synthetic data.
- **Dose selection.** No output is a dose recommendation, and none should be read as one.
- **Any tacrolimus product other than Advagraf prolonged-release.** The model, the therapeutic
  range and the limited-sampling cross-check all come from Advagraf studies. Immediate-release
  (twice-daily) tacrolimus is out of scope, and so is **LCPT (MeltDose / Envarsus XR)**, which is a
  different once-daily product with materially higher bioavailability and a later Tmax — it is not
  bioequivalent and its trough targets do not transfer. CORRECTED 2026-09-09: this entry previously
  said "the twice-daily branch exists but is deliberately unimplemented". The branch does not exist —
  it was REMOVED, and `Formulation` now admits exactly one value, named for the product rather than
  the generic `once_daily_er`, which had admitted two non-interchangeable drugs under one label.
- **Hepatic impairment, paediatrics, pregnancy, non-kidney transplant.** Untested.
- **Acute or time-critical decisions.** By design the horizon is days to weeks. Anything urgent
  routes to the transplant team's own contact path.
- **A patient far outside the derivation cohorts below.** The published equation's cohort has a
  mean weight of 54–58 kg.

### 4. Development details and input features

**Inputs:** dose times, amounts and reported status (taken / missed / vomited); measured
whole-blood concentrations with their times; body weight; haematocrit; CYP3A5 genotype where
tested, and the assumed expresser prevalence where not; formulation; fasted state of each sample.

**Priors** are the point estimates of ONE named published model — Fernández-Alarcón et al., *Front
Pharmacol* 2024;15:1456565, a two-compartment delayed-absorption model of Advagraf prolonged-release
tacrolimus in 138 de novo adult renal transplant recipients — carried with their published relative
standard errors. They are **not** invented defaults, and an earlier revision of this card that called
them "illustrative literature-derived defaults" was CORRECTED on 2026-09-09: it contradicted
`priors.py`, which states that every parameter comes from that single source, and it understated the
project's own sourcing in the document where sourcing is the whole claim.

What remains true, and is the real limitation, is narrower and sharper: the model is **de novo**,
fitted on days 5–15 post-transplant, while this product's patient is in **maintenance** months later.
That is an extrapolation, it is declared at every point of use, and it — not the provenance of the
numbers — is what must be resolved with a centre-specific or maintenance-phase model before any use
beyond demonstration. Population coefficients most frequently retained in
published models informed the covariate set: CYP3A5 genotype (retained in 88% of 68 reviewed
models), body size (29%), haematocrit (29%).

**No model was trained on patient data.** The PK core is a mechanistic model with Bayesian
individual fitting. Where a learned policy is later added, its training corpus is assembled only
through the consent-and-de-identification gate in `agent_pk/compliance/`.

### 5. Process used to ensure fairness

The single largest fairness risk here is **ancestry-linked, and it was found by adversarial
review rather than by intention.** CYP3A5 expresser status raises apparent clearance ~1.50× in the adopted model, and
expresser prevalence differs sharply by ancestry — roughly 19% in European, 49% in East Asian and
97% in African ancestry groups, derived from published CYP3A5\*3 allele frequencies.

Two consequences are handled explicitly:

- An **unknown genotype is treated as a mixture**, shifting the prior's mean as well as widening
  it. An earlier version widened only the variance, which biased a true expresser's predicted
  concentration upward by the full genotype factor and could suppress the escalation for exactly the
  population the product is for. A regression test now fails if that is reinstated.
- Expresser prevalence is an **explicit, deliberately-set field**, not an inherited constant. The
  0.30 default matches no single population and is documented as such.

**Not done:** no subgroup performance evaluation on real data, because there is no real data.
This is a gap, not a clean bill.

### 6. External validation process

**None on real patients.** Two internal checks stand in, and neither is external validation:

- Recovery of known parameters from seeded synthetic patients.
- An **independent cross-check** of fitted 24-hour exposure against a published, externally
  validated limited-sampling equation (C0-C1-C3-C6). Disagreement beyond tolerance is surfaced to
  the clinician, not smoothed away. This check is **unavailable for a trough-only fit**, and the
  product says so rather than implying the estimate was verified.

### 7. Quantitative measures of performance

**None are claimed, and the absence is deliberate.**

This model's performance figures are the ones its SOURCE reports, not ones we generated. The
population model is Fernández-Alarcón et al., *Front Pharmacol* 2024;15:1456565 (two compartments,
delayed first-order absorption, n = 138 de novo adult renal transplant recipients on Advagraf
prolonged-release tacrolimus); its parameter precisions are recorded as RSE% beside each constant in
`priors.py`, and its unexplained residual error is 28.2% CV. The independent cross-check is the
published limited-sampling equation (*Front Immunol* 2026, doi:10.3389/fimmu.2026.1710261), whose
own validation performance is R² 0.962, RMSE 11.614 ng·h/mL and MAPE 5.464% in 52 Japanese kidney
transplant recipients.

An earlier version of this card reported an exposure-bias table measured on our own seeded
synthetic patients. It has been removed rather than corrected. Those figures were properties of a
population prior that had been invented rather than sourced, and re-measuring them against a
published model changed both their size and, for the curve arm, their direction. A simulation of a
model against itself measures the simulation.

**What that means for a reader of this card:** Agent PK has no validated predictive performance of
its own, in any population. It is a research prototype that composes two published, cited
instruments; the performance you should judge it on is theirs, within their stated cohorts, and the
extrapolation beyond those cohorts is recorded in section 3.

**What we do not claim:** the published ~40% error reduction from multi-point sampling
(Umpiérrez et al., *Br J Clin Pharmacol* 2026;92(7):2109–2126) is measured against an *a priori*
prediction with no individual data at all. Our baseline already has four troughs on a
correctly-specified model, so the comparison is not like-for-like and we do not make it. An earlier
version of this paragraph reported that we "reproduce roughly 5% on that measure" — that figure has
been WITHDRAWN (2026-09-09), because it was obtained by simulating our own model against itself on a
patient we generated, which is the identical pattern this section disowns two paragraphs above.

**Interval semantics — corrected 2026-09-09, and material to how every output should be read.**
`predict_trough` reports a **prediction interval for a future MEASURED trough**, not a credible
interval on the patient's expected concentration. The distinction is the one Kümmel et al. set out
for pharmacometric models (*CPT Pharmacometrics Syst Pharmacol* 2018;7(2):95–102): a prediction
interval includes the inherent random variability of a future observation, and is therefore wider.
It matters because a therapeutic range is written against what the laboratory reports. Until
2026-09-09 the interval omitted the model's own 28.2% residual, which made it too narrow in one
direction only — it under-reached boundaries, so escalations that should have fired did not. The
residual is applied in the source's own PROPORTIONAL form, positivity-corrected by a bounded
resample; an intermediate revision used a log-normal residual and was reverted after a decorrelated
review showed it reported roughly three percentage points LOWER probability of being sub-therapeutic
than the source's form — the less conservative choice on the dangerous side. The
output now also carries **`probability_below` and `probability_above`**, the complement of
probability of target attainment, which is the quantity model-informed precision dosing reports and
the one that distinguishes a 6% risk from a 40% risk where a boundary-contact flag treats both alike.

**Escalation is judged on the RECOGNISED multi-sample measures, not on a single trough
(adopted 2026-09-09).** A one-off level moves for many reasons — a late dose, a meal, an
infection, the assay's own error — so transplant practice does not judge control from one
reading. Two established measures are now computed and reported:

- **Intrapatient variability (IPV)**, `CV = sigma/mu x 100%` over the patient's own troughs.
  **≥30% is the conventional high-variability line**, associated with de novo donor-specific
  antibodies, rejection and graft loss, and one of the few available signals for non-adherence.
  Source: Gavcovich TB, et al., *Front Transplant* 2025;4:1572928, doi:10.3389/frtra.2025.1572928
  (non-adherent median IPV 31% vs 20% adherent, p<0.001; AUC 0.772 for adherence). Review:
  Gonzales HM, et al., *Am J Transplant* 2020, doi:10.1111/ajt.16002. **Stated honestly: 30% is a
  convention across many studies rather than a value traced to one derivation, and the same
  source reports far more sensitive cut-points of 17–20%.** It is the line at which to look, not
  a diagnosis.
- **Time in therapeutic range (TTR)**, by Rosendaal linear interpolation — the fraction of TIME,
  not of samples, spent inside the range. TTR below 60% and below 75% has been associated with de
  novo DSA and acute rejection in the first year and with graft loss by five years; a separate
  analysis found an optimal cut-point of 78%. A dose-response is also reported: roughly **28%
  lower acute rejection risk per 10 percentage points of additional TTR**. Key IPV-and-TTR paper:
  *Transplantation* 2019, doi:10.1097/TP.0000000000002913. Cut-points are range-specific and the
  first-year analyses used 5–10 ng/mL, which is this project's range.

Note the two can disagree, and the product reports both for that reason: a patient may swing
widely (high IPV) while still holding a good TTR if the swings pass through the range rather than
sitting outside it.

**Haematocrit standardisation — adopted 2026-09-09, with its evidence stated precisely.**
Tacrolimus partitions heavily into red cells (blood-to-plasma ratio ~50 at haematocrit 0.45), so
an anaemic patient's whole-blood level is low for the same amount of drug in the body and a model
given the raw value **reads the anaemia as fast clearance**. The source model standardised
concentrations to 45% before fitting, so its parameters describe standardised values; observations
are now standardised on the way into a fit and predictions returned to the measured scale on the
way out. Formula: `Hct-adjusted = (0.45 / Hct) x measured`.

*Outcome evidence, as of July 2026:* a single-centre retrospective cohort of **344 adult liver
transplant recipients** (Vancouver General Hospital, 2018–2022; *Front Transplant* 2026,
doi:10.3389/frtra.2026.1878595, published 3 July 2026) found that each 1 ng/mL of delta-Tac — the
gap between adjusted and measured concentration — carried a **15% higher hazard of acute kidney
injury (HR 1.15, 95% CI 1.08–1.24, p<0.001)**, with AKI in 69.8% of the cohort within 90 days.
There was **no association with T-cell-mediated rejection (HR 0.93, 95% CI 0.77–1.14, p=0.50)**.

*What that does and does not establish — and this is the ordinary shape of medical evidence
rather than a hedge.* A correction can be right about the chemistry and still not be shown to
change what happens to patients. Establishing that takes studies designed for the question:
ideally prospective, across multiple centres, comparing the adjusted strategy against current
practice — because one retrospective centre cannot separate the adjustment's effect from
everything else that differs between sicker and healthier patients. The authors say so themselves:
residual confounding they could not adjust away; delta-Tac is derived partly *from* haematocrit so
it may partly track anaemia and illness severity rather than drug exposure; and the study "does not
evaluate a hematocrit-adjusted dosing strategy", so it cannot establish causality. They write that
the findings "warrant evaluation in independent cohorts" and that "replication studies are
currently underway". **So: mechanistically sound and pharmacokinetically validated; prospective
multi-centre outcome validation still outstanding. This is an evolving area and we cite it as
indicative, not settled.**

*Project design constraint, stated rather than assumed:* **this build does not assume anaemia.**
The demo patient sits at the reference haematocrit, where the correction is exactly the identity,
so no demo number depends on it. In real use the haematocrit is a value the clinician supplies,
and the correction then does real work — which is why it is implemented rather than deferred.

**Alert behaviour, measured 2026-09-09 — a first measurement, and a CEILING rather than an estimate.**
On 200 synthetic patients drawn from the model's own prior, the boundary-contact trigger
(`crosses_boundary`) caught **98%** of patients whose true trough was outside the range and left
**48%** of in-range patients un-alerted. Sensitivity is the safety-critical direction and it is high;
specificity is low, and at 90% interval mass a 5% tail reaching a boundary is enough to fire, so a
high false-alert rate is a property of that trigger rather than a defect in the fit. The figure is a
best case: those patients were drawn from the very prior the model fits against, with no model
misspecification, no inter-occasion variability and no haematocrit mismatch. It is reported here
because a triage tool whose alert burden is unmeasured cannot be evaluated, and because the
project's own design goal of "few, good alerts" is not met by boundary contact alone.

**Known structural limitation:** extended-release tacrolimus absorption is parameterised
differently by different published models — two gamma distributions in Riff et al. (*Br J Clin
Pharmacol* 2019), a delayed first-order rate in Fernández-Alarcón et al. (2024). This model uses
the second, because it uses that model's estimates and estimates are conditional on the structure
that produced them. So it is one published parameterisation among several, not the settled one,
and a fitted ka belongs to this model and must not be reported as another's.

Two further limits, both real: only **three of six** parameters are individualised (clearance and
central volume always, absorption only when post-dose samples identify it; peripheral volume,
distribution clearance and the 0.341 h lag are always held at population values), and the source
model is **de novo**, fitted days 5–15 post-transplant, while the intended patient is on
maintenance therapy. The exposure cross-check in §6 is what would detect either limit failing for
a given patient.

### 8. Ongoing maintenance of intervention implementation and use

Every clinician-facing output carries its complete basis — fitted parameters with credible
intervals, the number of observations behind them, the attribution, and every citation with its
population limit. Every access to patient data is logged with timestamp, actor, purpose and the
exact fields read. Deterministic gates (`ruff`, `mypy --strict`, 196 tests, `check-compliance`)
run before any change ships, and adversarial review by a lineage-diverse model panel runs on the
artefacts that matter.

### 9. Update and continued validation or fairness assessment schedule

No production update cadence exists, because there is no production deployment. The design
intent, recorded so it is not invented later: any learned policy is **frozen between scheduled
retrainings**, retraining draws only on a corpus assembled through the consent gate, patients who
withdraw are excluded from the next corpus, and every excluded patient is listed rather than
silently dropped. Fairness reassessment would need real subgroup data, which does not exist here.

---

**Disclaimer.** Agent PK is a hackathon research prototype. It is not a medical device, has not
been cleared or approved by any regulator, and must not be used to make any decision about the
care of a real patient. Nothing here is medical, legal or regulatory advice. Every patient, level,
dose and event in this repository is synthetic.
