# Guardrails — how Agent PK stays a decision-support tool and not a medical device

**This document is part of the product, not an appendix to it.** The regulatory boundary is what
decides the architecture: which of the two channels a sentence is allowed to appear in, and what
has to be on screen next to it. Everything in `src/` is shaped by this file.

Read the one-line version first: **Agent PK computes for a clinician and displays for a patient.**
The maths is shown in full to the clinician, who decides. The patient sees their own data and
their own clinician's own words, and never an interpretation the agent made up.

---

## 1. The two channels

Agent PK is one product with two software functions that carry different permissions. That split
is not a design preference — it is the structure the statute is written in, and 21 U.S.C.
§ 360j(o)(2) says so explicitly: where a product contains at least one function meeting the
paragraph (1) criteria and at least one that does not, *"the Secretary shall not regulate the
software function of such product described in subparagraph (A) as a device."* Keeping the
functions genuinely separable is therefore load-bearing, and it is enforced in code rather than in
prose — see `src/agent_pk/channel/`.

|  | **Patient channel** | **Clinician channel** |
|---|---|---|
| **Statutory basis** | § 360j(o)(1)(**D**) — transferring, storing, converting formats or displaying laboratory results, *findings by a health care professional with respect to those results*, and general background information | § 360j(o)(1)(**E**) — non-device clinical decision support, all four criteria met |
| **May show** | their own logged doses; their own returned results; the plan text their own clinician wrote; the sampling schedule; how to take a fingerstick; general background about the test | fitted CL/F, V/F and Ka with credible intervals; the predicted concentration interval; which plan boundary it crosses and when; the attribution of the change; every citation and its limits |
| **May say** | "your team has been notified"; "your next draw is Tuesday at 08:00"; "an evaluation by your clinician may be helpful" | "flag for review"; "urgent review"; "consider a dose reduction"; "schedule an additional PK sample"; "escalate to the transplant team" |
| **Never** | a predicted number · an in-range / out-of-range verdict · a dose · a named disease risk · an interpretation of any result | — |

The patient channel is a **projection** of the clinician view, and the projection is typed so that
it *cannot* carry an interval, a boundary verdict or an attribution. A test asserts this. It is the
same class of defect the session-1 panel caught three times in the covariance guard — a boundary
that is asserted in a comment rather than enforced by the type is a boundary that will eventually
leak.

### Why the general-wellness route was rejected

An earlier draft placed the patient channel under § 360j(o)(1)(B), the healthy-lifestyle exemption.
**It does not reach a transplant patient**, and the reason is in the text: (B) requires the function
be *"unrelated to the diagnosis, cure, mitigation, prevention, or treatment of a disease or
condition."* FDA's *General Wellness: Policy for Low Risk Devices* final guidance (January 2026)
adds that such a product's alerts may not name a specific disease, characterise an output as
abnormal or pathological, carry clinical thresholds, or provide ongoing disease-management
monitoring. A tacrolimus trough plotted against a therapeutic window is all four at once.

One primitive from that guidance survives and is used: **a general notification that an evaluation
by a health care professional may be helpful**, carrying no disease name and no threshold. That is
the strongest sentence the patient channel is permitted to generate on its own.

---

## 2. The four criteria, and what satisfies each

The governing document is FDA's **Clinical Decision Support Software: Guidance for Industry and
Food and Drug Administration Staff, January 2026** (docket **FDA-2017-D-6569**), which replaced the
28 September 2022 version. It construes § 520(o)(1)(E) of the FD&C Act, codified at 21 U.S.C.
§ 360j(o)(1)(E).

### Criterion 1 — not a medical image, IVD signal, or pattern from a signal acquisition system

> *"unless the function is intended to acquire, process, or analyze a medical image or a signal from
> an in vitro diagnostic device or a pattern or signal from a signal acquisition system…"*

**What we do.** Agent PK takes a *discrete reported concentration value* — a number a laboratory has
already produced, reported and released — together with dose times, weight, haematocrit and
genotype. It acquires no image, processes no waveform, and connects to no instrument. It does not
sit between an assay and its result.

**The honest limit, stated rather than buried.** A tacrolimus trough originates from an in vitro
diagnostic assay, and the agent proposes *when a sample should be taken*. FDA's long-standing
reading distinguishes a discrete released laboratory **result** from a **signal** — a continuous or
waveform output of an acquisition system — and Agent PK is squarely on the result side of that
line. But the distinction is interpretive rather than defined in the statute, and the microsampling
workflow (where a patient collects the specimen at home) is closer to the boundary than a venous
draw reported by a hospital lab. **We do not claim this question is closed.** It is the first thing
a regulatory reviewer should be pointed at, and it is why the agent never touches specimen handling,
assay configuration, or result release — it reads a number that a laboratory has already signed out.

### Criterion 2 — displaying, analysing or printing medical information

> *"…for the purpose of displaying, analyzing, or printing medical information about a patient or
> other medical information (such as peer-reviewed clinical studies and clinical practice
> guidelines)"*

**What we do.** Both halves are used deliberately. The patient's own dose and concentration history
is the first half. The retrieved published evidence — the population pharmacokinetic model, the
sampling-strategy paper, the interaction literature, the label — is the second, and the statute
names peer-reviewed clinical studies and practice guidelines explicitly. Every clinician-facing
claim in Agent PK carries its citation for exactly this reason.

### Criterion 3 — recommendations to a **health care professional**

> *"…supporting or providing recommendations to a health care professional about prevention,
> diagnosis, or treatment of a disease or condition"*

**What we do.** Every recommendation — flag for review, urgent review, consider a dose change,
schedule an additional PK sample, escalate — is addressed to a clinician and appears only in the
clinician channel. **The patient is never the recipient of a recommendation.** The patient receives
logistics: when the draw is, how to take the sample, that their team has been told.

The January 2026 guidance **relaxed** this criterion in one respect that helps us: FDA will now
exercise enforcement discretion for software producing a *single* clinically appropriate
recommendation, reversing the 2022 position that a list of options was required. Agent PK does not
depend on that relaxation — it presents the boundary crossing and the options together — but it
means a single unambiguous output would not by itself take us out of the exemption.

### Criterion 4 — the clinician can independently review the basis

> *"…enabling such health care professional to independently review the basis for such
> recommendations that such software presents so that it is not the intent that such health care
> professional rely primarily on any of such recommendations to make a clinical diagnosis or
> treatment decision regarding an individual patient."*

This is the criterion that decides the architecture, and it is where most AI clinical tools fail.
FDA's January 2026 language requires *"contextually relevant information about the software logic"*
and about *"the reliability of the clinical data and evidence driving the outputs,"* presented
*"in a manner that promotes useability and avoids information overload, including prioritizing the
most decision-relevant information and making additional detail available as appropriate."*

**What we do — and the rule this forces on the machine learning.**

Every number the clinician sees is derived from an explicit pharmacokinetic calculation they can
reproduce:

- the published two-compartment, delayed-absorption population model, written out and cited
  (Fernández-Alarcón et al., *Front Pharmacol* 2024;15:1456565);
- this patient's fitted CL/F, V/F and Ka, with credible intervals and the number of observations
  they rest on;
- the predicted concentration interval, and which plan boundary it crosses, and when;
- the attribution — how much of the change is genotype, how much is the new interacting drug, how
  much is adherence, how much is unexplained;
- the source of every coefficient, and the population it was derived in.

**The learned components never form part of the displayed basis.** This is a hard rule:

> A neural policy cannot satisfy criterion 4, because its basis cannot be reviewed. Therefore the
> learned policy in Agent PK **only orders and schedules options whose complete basis is already on
> screen**. It never authors a reason, never contributes a number the clinician is asked to trust,
> and never appears as the justification for anything.

This is the same principle the wider system runs on: the deterministic layer is the authority, the
model proposes. Here it is also the difference between a non-device and a device.

**The sampling offer is the clearest instance.** When the agent judges that more data would sharpen
this patient's profile, it does not act. It shows the clinician what the extra samples would buy —
*"three extra draws on Tuesday, alongside the trough already scheduled, would narrow this
patient's exposure estimate by about half — and make it independently checkable against the
published equation for the first time"* — and the clinician decides. Every figure on that card is
computed at runtime from `build_sampling_offer`; none is written into the interface. They then
watch the points land on the curve and can see for themselves that the profile is calibrated to
this patient rather than to a population. Human judgement stays in the loop at the point where the model would
otherwise have quietly taken over.

---

## 3. Nothing Agent PK produces is time-critical

The January 2026 guidance moved time-critical decision-making out of criterion 3 and into
**criterion 4**: software supporting a time-critical decision cannot, in FDA's view, permit
meaningful independent review, and is therefore a device.

Agent PK is designed so that this never arises:

- Its unit of output is **when to look next**, on a horizon of days to weeks. It closes a gap
  between monthly blood draws; it is not an acute alerting system.
- It has **no emergency pathway of its own**. Where a situation is genuinely urgent, the agent's
  action is to surface the transplant team's existing contact route to the patient and to notify the
  clinician — it does not adjudicate the emergency, triage its severity, or stand between the
  patient and the people whose job that is.
- It never produces an output whose value depends on being acted on within minutes or hours.

If a future feature would require an immediate response, that feature is a device function and
belongs behind a device pathway, not in this product.

---

## 4. The limits of the evidence, disclosed

Criterion 4 makes the reliability of the underlying data part of what must be shown, so it is
stated here and in the clinician view rather than left in a footnote.

- **The sampling equations are from a small, ethnically specific cohort.** The extended-release
  limited-sampling equations come from 52 Japanese kidney transplant recipients (30 patients / 48
  observations in derivation; 27 / 42 in validation), mean weight 54–58 kg. Applying them to a 70 kg
  reference patient is an extrapolation, and the clinician view says so at the point of use.
- **The population coefficients ARE a published model, and the limitation is its POPULATION, not
  its provenance.** CORRECTED 2026-09-09 — this entry previously called them "illustrative"
  defaults, contradicting `priors.py`, which states that every parameter is a point estimate from
  Fernández-Alarcón et al., *Front Pharmacol* 2024;15:1456565, carried with its published relative
  standard errors. The real limitation: that model is **de novo**, fitted days 5–15
  post-transplant, and this product's patient is in maintenance. Clearance and its covariates move
  over that interval, so every number inherits an extrapolation. It must be replaced with a
  maintenance-phase or centre-specific model before any use beyond demonstration — for that reason,
  not because the numbers were made up.
- **CYP3A5 expresser prevalence is population-dependent and must be set deliberately.** The default
  of 0.30 matches no single population: derived from published CYP3A5\*3 frequencies, expresser
  prevalence is roughly 19% in European, 49% in East Asian and 97% in African ancestry groups. An
  unset prevalence is a real source of bias in exactly the direction that suppresses an escalation,
  which is why it is an explicit field rather than a silent constant.
- **The interaction table gives direction, never magnitude.** It says which way a level is likely to
  move and triggers a human review. It does not estimate a size, and it is not a substitute for the
  transplant team's own interaction check.
- **The reinforcement-learning evidence is transferred by analogy.** The offline conservative
  Q-learning design is taken from ICU vasopressor dosing, and the contextual-bandit result is from
  clinical-trial arm assignment, not symptom triage. Neither has been validated in this setting, and
  the writeup says so where the figures appear.
- **Every patient in this repository is synthetic.** No real patient data was used and none is
  present. The pharmacokinetic module has no file or network path that could acquire any.

---

## 5. Patient data: HIPAA, consent, and what actually does the work

### The one move that removes most of the problem

Model training on patient data raises authorization, IRB and research questions — **unless the
data is not patient data any more.** Under 45 CFR 164.514(b), once information is de-identified by
the Safe Harbor method or by Expert Determination it is no longer protected health information,
the Privacy Rule stops applying to it, and **neither individual authorization nor IRB approval is
required to use it.**

Agent PK therefore de-identifies **before** any training, and the de-identification is the legal
mechanism. That is enforced in `agent_pk/compliance/`, not asserted here.

### Where consent still matters, and what it does not do

**A tick box is not a HIPAA authorization.** 45 CFR 164.508(c) requires specific elements — the
information described, who discloses, who receives, the purpose, an expiration, the right to
revoke and how, a redisclosure statement, and a dated signature. Published analysis is blunt that
a general consent to "research and quality improvement" almost certainly does not satisfy HIPAA's
authorization requirements for commercial AI training. **So the claim that one checkbox "covers
IRB, HIPAA and FTC requirements" is not one this project makes.** It would be found wrong quickly,
and it is not needed, because the training path is de-identified.

The consent we do record is worth having on its own terms — the patient's control over their own
data — and its scopes are kept apart because the law keeps them apart:

| Scope | What it is legally | What it permits |
|---|---|---|
| **Own care** | Treatment and health care operations | Using this patient's data to look after this patient |
| **De-identified improvement** | Not PHI once de-identified, so outside the Privacy Rule | Model training on Safe-Harbor-stripped records. Revocable at any time |
| **Identified research** | Research under 164.501 — generalizable knowledge | **Refused outright by the corpus assembler**, even when granted. It needs a 164.508 authorization or a 164.512(i) IRB waiver, which no in-app tick box supplies |

The patient-facing wording, unchanged from the operator's own draft because it is good and its two
halves happen to track the legal line exactly ("for me" is operations; "for other patients" is
generalizable knowledge):

> *I consent to my tacrolimus levels, dosing history and symptom reports being used to improve the
> prediction accuracy of this assistant for me and for other patients (de-identified). I understand
> I can withdraw this consent at any time.*

### What is enforced in code

- **Consent is tested at the moment of USE, not of collection.** A patient who withdrew yesterday
  is out of a corpus assembled today. Revocation is recorded rather than erased, so a use that was
  lawful when it happened stays auditable as such.
- **Exclusions are carried, never dropped.** A corpus that silently omits the patients who
  withdrew is indistinguishable from one that never had them.
- **The pseudonym cannot be derived from the patient.** 164.514(c) permits a re-identification
  code only if it is not derived from the individual's information and cannot be translated back.
  A SHA-256 of a medical record number fails both — it is derived by construction and reversible
  by enumeration over a hospital's small identifier space. `pseudonym()` therefore takes no
  arguments at all, so a caller holding an MRN cannot pass it in even by accident.
- **De-identification is an allowlist, not a denylist.** A denylist passes through the field
  nobody thought of, which is the one that identifies.
- **There are no dates in a training record.** The PK core has used hours-since-a-per-patient
  reference instant since session one, for numerical reasons — which happens to remove the Safe
  Harbor category hardest to strip from clinical time-series data.
- **Minimum necessary is evidenced, not asserted.** An access does not get logged after the fact;
  the read *is* the projection. `AuditLog.access()` returns only the fields the caller declared
  and writes the record in the same call, so a caller cannot read more than it declared and cannot
  read without logging. Refusals are logged too.

**Honest limits.** The audit log is in-memory and provides no tamper-evidence, signing or
durability — production needs append-only storage with integrity protection. It records what the
application did, not what someone did around it. It does not authenticate the actor. And Safe
Harbor is a rule about *fields*: high-dimensional clinical data still carries quasi-identifiers in
combination, so meeting the regulatory standard is not the same as the data being unlinkable.

### Which privacy regime applies is a deployment question, not a badge

**HIPAA and the FTC Health Breach Notification Rule are close to mutually exclusive** — the HBNR
covers vendors of personal health records that are **not** covered by HIPAA. So:

- **Under a BAA with a transplant centre** (the intended path): Agent PK is a business associate,
  HIPAA applies, HBNR does not.
- **Direct to consumer with no BAA:** HIPAA does not reach it and the **HBNR does**. Its 2024
  amendments matter here: PHR identifiable health information now expressly includes health data
  *inferred from non-health data*, and the notification trigger became unauthorized **disclosure**,
  not merely unauthorized acquisition.

The design satisfies both so either deployment works, but the slide should say which one it is
rather than claiming both at once.

## 6. State AI-in-healthcare law, and what actually binds

Verified against source for this build. **Three of the eight commonly-cited statutes do not apply
to this product**, and saying so is worth more than a longer list:

| Law | In force | Applies to Agent PK? |
|---|---|---|
| **California AB 489** — AI may not use protected health-professional titles or imply licensed care | 1 Jan 2026 | **Yes.** The agent never uses a clinical title, never implies a licensed clinician is speaking, and says it is software |
| **California AB 3030** — GenAI patient communications need an AI disclaimer and a human contact path | 1 Jan 2025 | **Yes** — and its **physician-review exemption** fits our architecture: a communication reviewed by a licensed provider is exempt, which is exactly the clinician-in-the-loop design |
| **Texas HB 149 (TRAIGA)** — providers must disclose AI use to patients by the date of service | 1 Jan 2026 | **Yes.** Disclosure is built into the patient channel |
| **Texas SB 1188** — AI-produced records reviewed by a physician before entering the record; **EHRs with Texas patient data stored in the US** | 1 Sep 2025 (localisation 1 Jan 2026) | **Yes**, both limbs. The data-localisation requirement is a deployment constraint on where anything is hosted |
| **Illinois HB 1806 (WOPR)** | 4 Aug 2025 | **No** — behavioural health only |
| **Nevada AB 406** | 1 Jul 2025 | **No** — mental/behavioural health only |
| **Utah HB 452** | 7 May 2025 | **No** — mental health chatbots only |
| **ONC HTI-1 §170.315(b)(11)** Predictive DSI source attributes | — | **Not directly** — it binds certified health IT. But our `MODEL-CARD.md` is written to its nine source-attribute categories so it drops into a certified environment |

The three that do not apply nonetheless encode principles this design already meets — AI may not
make independent clinical decisions, a licensed professional reviews, disclose that it is AI, and
do not sell or share individually identifiable health information. **Claiming compliance with laws
that do not bind us would be weaker, not stronger, than saying which ones do.**

### Unauthorized practice of medicine

On 1 May 2026 the **Pennsylvania State Board of Medicine** petitioned the Commonwealth Court
against **Character Technologies, Inc.** — the first action of its kind — alleging the
unauthorized practice of medicine after a chatbot held itself out as a licensed psychiatrist and
supplied a fabricated Pennsylvania licence number. The lesson is narrow and directly applicable:
**never a clinical title, never an implied licence, never a claim to be a clinician.** Agent PK
addresses recommendations to a clinician, identifies itself as software, and always exposes a
human contact path.

## 7. Hong Kong — the fastest path to a live deployment

**This is the strongest deployment story the project has, and it is worth leading with rather than
burying at the end of an international footnote.** Hong Kong imposes materially fewer preconditions
than the US, and Agent PK was built to the stricter standard, so the HK obligations are already met
as a by-product rather than as extra work.

### What Hong Kong does NOT require

| | Hong Kong | Contrast |
|---|---|---|
| **Device registration** | **Not required.** MDACS listing is legally voluntary | US needs the CDS exemption argued; UK would need a device route |
| **Privacy impact assessment** | **Not mandated** by the PDPO for private-sector processing — recommended good practice only | GDPR mandates a DPIA for high-risk processing |
| **Data localisation** | **None.** PDPO s.33, which would restrict transfers out of Hong Kong, has never been brought into force and has no timetable — in force since 1996 without it | **Texas SB 1188 requires US storage** of Texas patient EHR data from 1 Jan 2026 |
| **Breach notification** | **Not mandatory today.** The PCPD strongly recommends voluntary notification where there is a real risk of harm | FTC HBNR notification is mandatory and its 2024 trigger is unauthorized *disclosure* |

So the operating position is: **comply with the six Data Protection Principles, and that is the
substance of it.** No registration, no mandatory assessment, no localisation constraint.

### The one refinement — DPP3 *is* a consent requirement

"No explicit consent beyond the DPPs" understates one of the DPPs. **DPP3 requires "prescribed
consent" — express, given voluntarily, and withdrawable only in writing — before personal data is
used for a NEW PURPOSE**, meaning any purpose other than the one it was collected for or one
directly related to it. Using a patient's data to improve the model *for other patients* is a new
purpose; using it to care for that patient is not.

**The same move that resolves this in the US resolves it here, and by the same mechanism.** The
PDPO defines personal data as information from which the individual's identity is *practicably
ascertainable*; anonymised data falls outside that definition, so the Ordinance does not reach it.
Agent PK de-identifies before any training, which takes the training path out of DPP3 exactly as it
takes it out of HIPAA authorization. One architectural decision, two jurisdictions.

Two things to keep an eye on rather than assume away:

- Hong Kong's test is **purposive** ("practicably ascertainable"), not a fixed field list like HIPAA
  Safe Harbor. Our Safe Harbor projection would generally satisfy it, but the quasi-identifier
  residual recorded in §5 is if anything more relevant here, not less.
- A **proposed widening of "personal data" from *identified* to *identifiable*** persons is under
  consideration. It would raise the de-identification bar, and it is the single reform most likely
  to affect this design.

Breach notification is likewise under active reform: the government is consulting in 2026 on a
mandatory regime with notification within **five business days** where there is a real risk of
significant harm. Building to the FTC HBNR standard now means that reform costs us nothing.

### Software as a medical device does exist in Hong Kong — it is just voluntary

Worth stating precisely, because "no device registration needed" can be heard as "no framework
exists". On **29 December 2023 the Medical Device Division issued Technical Reference TR-007
(Software Medical Devices and Cybersecurity)**, which formally defines Software as a Medical Device
and Software in a Medical Device, sets classification rules, and states the technical documentation
expected for MDACS listing. It also carries AI-specific post-market expectations — tracing
real-world performance, guarding against concept drift, and reporting through a local
representative.

None of that is compulsory. MDACS remains legally voluntary, though it is **de facto mandatory for
commercial market access**, and since March 2026 Department of Health procurement requires listing.
MDACS was created in 2004 as a transitional step toward a full statutory regime, so the direction of
travel is toward mandatory, not away from it.

**What this means for us:** we can go live in Hong Kong now without listing. If we later choose to
list — which government procurement would require — TR-007's AI post-market expectations map onto
things this build already does: performance is traced against a published equation, drift is exactly
what the personal-baseline detector watches for, and the model card is already written to a
recognised source-attribute structure.

### One caution carried over

The Pennsylvania unauthorized-practice action in §6 is a US case, but the underlying rule is not
jurisdictionally exotic — Hong Kong restricts the practice of medicine to registered medical
practitioners under its own registration regime. The design answer is the same one already built:
recommendations are addressed to a clinician, never to the patient; the agent identifies itself as
software; it never uses a clinical title or implies a licence. We have not taken Hong Kong advice on
this point, and the claim here is about our design, not about Hong Kong law.

## 8. The compliance slide

> **In production, we operate under a BAA with the transplant centre. Patient data is de-identified
> before any model training — which is what takes training out of HIPAA's authorization
> requirement entirely, not the consent checkbox. Minimum necessary is enforced at the API layer:
> a read returns only the fields it declared, and logs them. All patient data is encrypted, never
> shared with third parties, and every access is logged with timestamp, actor and purpose.**
>
> **Agent PK is designed as FDA-exempt non-device CDS under 21 U.S.C. § 360j(o)(1)(E). The agent
> discloses that it is AI, never uses clinical titles, always provides a human contact path, and a
> clinician reviews every recommendation before it enters the medical record. Compliance is built
> into the architecture — the patient channel is structurally incapable of carrying an
> interpretation, and a withdrawn patient cannot reach a training corpus.**

### On international scope — HK leads, UK is narrowed

**Lead with Hong Kong.** It is the only jurisdiction where this can go live immediately, and the
work is already done:

> *We built Agent PK to the US standard, which is the strictest of the three. That makes Hong Kong
> a launch decision rather than a compliance project: MDACS listing is voluntary, no privacy impact
> assessment is mandated, and PDPO section 33 has never been brought into force, so there is no
> data-localisation constraint — unlike Texas, which requires US storage from January 2026. We
> operate under the six Data Protection Principles, and because we de-identify before any model
> training, the DPP3 new-purpose consent requirement does not reach the training path — the same
> architectural decision that takes it out of HIPAA authorization.*

**The UK claim needs narrowing, and the reason is worth understanding rather than glossing.** The
MHRA's draft Medical Devices (Amendment) Regulations 2026 (published 8 May 2026; reforms 2026,
implementation 2027) let the MHRA *rely on an existing authorisation* from a comparable regulator —
Australia, Canada or the USA. **An FDA-exempt product has no US authorisation to rely on**, because
being outside the device definition is the opposite of having been authorised. The UK also has no
statutory equivalent of the US non-device CDS carve-out; UK software qualifies as a medical device
on intended purpose, and Agent PK's intended purpose would likely make it one.

> *Our US path is the non-device CDS exemption and our first live deployment would be Hong Kong.
> The UK has no equivalent statutory carve-out, so a UK deployment would go through the medical
> device route on its own merits — the reliance pathway does not help a product that was never
> authorised in the first place.*

## 9. Disclaimer

**Agent PK is a research prototype built for a hackathon. It is not a medical device, it has not
been cleared or approved by any regulator, and it must not be used to make any decision about the
care of a real patient.**

Nothing in this repository is medical advice, and nothing in this document is legal or regulatory
advice. The analysis above is the project team's own reading of publicly available law and guidance,
recorded so that it can be checked and argued with — not an opinion anyone should rely on. Any real
deployment would require a proper regulatory assessment, clinical validation in the intended
population, and the involvement of the transplant service whose patients it would touch.

**If you are a transplant patient: talk to your transplant team. Do not change anything about how
you take your medicine because of anything a piece of software told you.**

---

## Sources

- 21 U.S.C. § 360j(o) — <https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title21-section360j&num=0&edition=prelim>
- FDA, *Clinical Decision Support Software: Guidance for Industry and Food and Drug Administration
  Staff*, January 2026, docket FDA-2017-D-6569 —
  <https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-decision-support-software>
- FDA, *General Wellness: Policy for Low Risk Devices*, final guidance, January 2026
- Umpiérrez M, Maldonado C, Guevara N. *Accelerating tacrolimus model-informed precision dosing in
  kidney transplant recipients: model evaluation and refinement strategies.* Br J Clin Pharmacol
  2026;92(7):2109–2126. <https://doi.org/10.1002/bcp.70447>
- *Establishment of accurate estimation equations for area under the concentration curves using
  simultaneous limited sampling for extended-release tacrolimus and mycophenolic acid in kidney
  transplant recipients.* Front Immunol 2026. <https://doi.org/10.3389/fimmu.2026.1710261>
- FDA Prograf (tacrolimus) prescribing information — food effect, interactions
- Zou WY, Feng J, Kalimouttou A, Zhang JY, Seymour CW, Pirracchio R. *Realistic CDSS drug dosing
  with end-to-end recurrent Q-learning for dual vasopressor control.* <https://arxiv.org/abs/2510.01508>
- Varatharajah Y, Berry B. *A contextual-bandit-based approach for informed decision-making in
  clinical trials.* Life 2022;12:1277. <https://doi.org/10.3390/life12081277>
- 45 CFR 164.508 (authorization), 164.501 (research / health care operations), 164.512(i)
  (IRB or Privacy Board waiver), 164.514(b)-(c) (de-identification and re-identification codes),
  164.502(b)/164.514(d) (minimum necessary), 164.312(b) (audit controls)
- FTC Health Breach Notification Rule, 2024 amendments, effective 29 July 2024 —
  <https://www.ftc.gov/legal-library/browse/rules/health-breach-notification-rule>
- ONC HTI-1 final rule, Decision Support Interventions criterion 45 CFR 170.315(b)(11) —
  <https://www.healthit.gov/test-method/decision-support-interventions/>
- California AB 489 (2025); California AB 3030 (2024)
- Texas HB 149 (TRAIGA) and Texas SB 1188 (2025)
- Illinois HB 1806 (2025); Nevada AB 406 (2025); Utah HB 452 (2025) — behavioural/mental health,
  cited as not applicable
- Pennsylvania State Board of Medicine v. Character Technologies, Inc., Commonwealth Court,
  petition filed 1 May 2026
- MHRA draft Medical Devices (Amendment) Regulations 2026 (WTO notification, 8 May 2026);
  Hong Kong Medical Device Administrative Control System (MDACS), voluntary listing
- Riff C et al. Population pharmacokinetic model and Bayesian estimator for 2 tacrolimus
  formulations in adult liver transplant patients. Br J Clin Pharmacol 2019.
  <https://doi.org/10.1111/bcp.13960>
- Hong Kong Personal Data (Privacy) Ordinance (Cap 486) — DPP1–DPP6; DPP3 "prescribed consent" for
  a new purpose; s.33 (cross-border transfer) never brought into force; breach notification
  voluntary, mandatory regime under consultation 2026 —
  <https://www.pcpd.org.hk/english/data_privacy_law/ordinance_at_a_Glance/ordinance.html>
- PCPD, *Artificial Intelligence: Model Personal Data Protection Framework*, 11 June 2024 —
  <https://www.pcpd.org.hk/english/artificial_intelligence/index.html>
- PCPD, *Privacy Impact Assessment* information leaflet (PIA recommended, not mandated) —
  <https://www.pcpd.org.hk/english/resources_centre/publications/files/InfoLeaflet_PIA_ENG_web.pdf>
- Hong Kong Medical Device Division, Technical Reference **TR-007:2023(E)** — Software Medical
  Devices and Cybersecurity (SaMD/SiMD definitions, classification, AI post-market expectations),
  issued 29 December 2023 — <https://www.mdd.gov.hk/filemanager/common/mdacs/TR007.pdf>
