# What we ask the patient to record, and why it is not a food diary

**Status: DESIGNED, not built.** No field in this document exists in `src/` yet. It answers a
design question — *what dietary information is worth collecting from a patient at all* — and the
answer is narrower and more defensible than the obvious one.

---

## 1. The question

Food is not a nuisance variable for tacrolimus. It is one of the largest single influences on the
shape of the curve we are fitting. In healthy volunteers given a single 5 mg oral dose, a high-fat
meal moved the pharmacokinetics like this:

| | Fasting | Low-fat meal | High-fat meal |
|---|---|---|---|
| Cmax (ng/mL) | 25.6 | 9.03 | **5.88** |
| AUC(0–∞) (ng·h/mL) | 272 | 201 | **181** |
| Tmax (h) | 1.37 | 3.20 | **6.47** |

*Bekersky, Dressler & Mekki, **J Clin Pharmacol** 2001;41(2):176–182 (PMID 11210398,
doi:10.1177/00912700122009999). Fifteen healthy male volunteers, three-period randomised crossover.
Differences between fasting and each fed state were statistically significant (p < 0.05); terminal
half-life (~34 h) was unaffected.*

Read the Tmax row again. **Fed, the peak arrives roughly 4.7× later.** Our calibration protocol
takes samples at 0, 1, 3 and 6 hours after a dose. A sample drawn at 1 hour lands on the rising
limb in a fasted patient and nearly at baseline in a fed one. The same number means two different
things depending on a fact the blood tube does not record.

So the question is not *should we collect dietary data* — we have to. The question is **what can a
patient actually report accurately enough to be worth acting on.**

## 2. Why the obvious design is the wrong one

The instinctive design is a food log: what did you eat, how much fat. The dietary-assessment
literature says plainly that this does not work, and it does not work even under research
conditions far better than a transplant patient tapping a phone at 7am.

Measured against recovery biomarkers — doubly labelled water for energy, 24-hour urine for protein,
potassium and sodium — in 1,075 adults aged 50–74:

- Energy intake was **underestimated by 15–17%** using multiple automated 24-hour recalls, the
  *best-performing* instrument tested.
- **18–21%** using 4-day food records.
- **29–34%** using food-frequency questionnaires.
- Underreporting was **systematic** — every self-report instrument was biased low, not noisy around
  the truth — and worse among people with obesity.

*Park, Dodd, Kipnis, Thompson, Potischman, Schoeller, Baer, Midthune, Troiano, Bowles & Subar,
**Am J Clin Nutr** 2018;107(1):80–93 (PMID 29381789, doi:10.1093/ajcn/nqx002).*

A systematic 15–34% underestimate is not a correctable offset — the size of the bias varies between
people, which is exactly the property that makes it useless for an individualised model. Asking a
patient how many grams of fat they ate would import a large, person-specific, unmeasurable error
into a model whose entire purpose is to be accurate for that specific person.

**But the same literature contains the escape route.** In that study, *absolute* intakes were
systematically wrong while **nutrient densities — relative composition — matched biomarker values**
for protein and sodium. Relative comparisons survive where absolute quantities do not. That finding
is the design principle for everything below.

## 3. The design: annotate the sample, do not model the meal

Two decisions follow, and they are the whole of it.

**Decision 1 — record the dose–food *relationship*, not the food.** What changes the curve is
whether the drug met food in the gut, and how close together they were. That is a timing fact, and
patients report timing far better than they report quantity. It is also the fact clinical practice
already turns on: patients are instructed to take tacrolimus **consistently** with respect to
meals, precisely because the fed/fasted difference is large.

**Decision 2 — where a judgement about the meal itself is unavoidable, ask for it relative to that
patient's own usual, never in absolute units.** "Heavier than your normal breakfast" is a
within-person comparison. It is the kind of judgement Park et al. found survives, and it is
coherent with a product whose every other baseline is the patient's own.

### The fields

| Field | Type | Why it earns its place |
|---|---|---|
| `dose_taken_at` | timestamp | Already required by the model — every prediction is on the dose time axis. |
| `food_within_window` | bool | The single highest-value bit. Fed vs fasted is a 4.7× Tmax difference. |
| `minutes_dose_to_nearest_meal` | int, signed | Negative = dose before food, positive = dose after. Direction matters: the gut state the drug meets is not the same in the two cases. |
| `meal_size_vs_usual` | enum: `lighter` \| `usual` \| `heavier` \| `much_heavier` | A within-person relative judgement (§2). Never grams, never calories. |
| `typical_day` | bool | One question that catches everything we did not think to ask — illness, travel, a missed meal, a schedule change. |

Five fields. Four are answerable in a couple of taps; none requires the patient to estimate a
quantity they cannot estimate.

### What these fields are FOR — and this is the part that keeps us out of trouble

They are a **sample-validity annotation**. They are **not** covariates entering the pharmacokinetic
model, and no coefficient is fitted to them.

Concretely, they do three things:

1. **Decide whether a sample is interpretable.** `SampleAppointment` already carries
   `fasted_required`. When the appointment required fasted sampling and `food_within_window` is
   true, the run was conducted under different conditions than the protocol assumed — the clinician
   is told, and can discard or repeat it. Today that mismatch is undetectable.
2. **Explain an outlier before it becomes an alert.** A level below a patient's own baseline has a
   very different meaning when the dose was taken 20 minutes after a heavy meal than when nothing
   changed. This is the difference between a useful flag and a false alarm, and the false-alert rate
   is the metric this product lives or dies on.
3. **Give the clinician the context they would have asked for anyway** — in the two-channel design,
   as data, not as an interpretation.

**Why not make them model covariates?** Because the honest magnitude is not available. Bekersky
measured healthy volunteers on a standardised high-fat meal, not a transplant patient's actual
Tuesday. Using a published food-effect coefficient to correct an individual's fitted curve would
be the same error this project already made once and withdrew: borrowing a number measured in one
setting and applying it as though it transferred. **Direction and interpretability, not magnitude
— the same rule the interaction check follows.**

## 4. The clinician-authored route already exists

The fixed set above is the *floor* — the fields that are universal because the food effect is
universal. Anything beyond it is the clinician's call, and the mechanism for that is already built:
`ConcurrentObservation` in `src/agent_pk/channel/views.py` lets a clinician attach their own
tracking instruction to a patient, carried verbatim to the patient app, with
`authored_by_clinician` enforced as a checked field so the agent cannot invent one.

So the answer to "can the clinician define their own fields" is **yes, and that half is done.**
What this document adds is the default set that should be there before any clinician customises
anything.

## 5. Honest limits

- **Nothing here is built.** Fields, the mismatch check against `fasted_required`, and the
  outlier-explanation path are all design.
- **Bekersky is healthy volunteers on immediate-release tacrolimus at a single 5 mg dose.** Our
  patient is a transplant recipient on Advagraf prolonged-release at steady state. The direction
  and rough scale of the food effect are well established across formulations; the specific numbers
  in the table are not our patient's numbers, and the table is in this document to justify a *design
  decision*, not to be applied to anyone.
- **`meal_size_vs_usual` is a self-report and inherits self-report's problems.** The Park finding
  supports relative over absolute; it does not make relative accurate. It is treated as a hint for
  a human, never as a model input.
- **The FDA Prograf label reports the food effect on a different AUC window (AUC(0–96), ~37%
  reduction) than Bekersky's AUC(0–∞) (~33%).** Both describe the same study; quote whichever
  source is cited and do not mix them. Label figures on dose *timing* relative to a meal have not
  been verified against the current label by this session — **verify before putting them in the
  deck.**
