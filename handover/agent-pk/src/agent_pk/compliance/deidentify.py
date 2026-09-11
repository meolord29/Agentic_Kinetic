"""deidentify.py — Safe Harbor de-identification, and the pseudonym rule people get wrong.

De-identification is the step that does the most legal work in this product. Under 45 CFR
164.514(b) Safe Harbor, once the eighteen identifier categories are removed and the holder has no
actual knowledge that the remainder could identify the individual, the information is no longer
protected health information. The Privacy Rule then does not apply to it, and neither individual
authorization nor IRB approval is required to use it. That is what takes model training out of
the authorization question entirely.

**THE MISTAKE THIS MODULE EXISTS TO PREVENT: a hash of the medical record number is not a
compliant pseudonym.** 45 CFR 164.514(c) permits a re-identification code only if it is *not
derived from or related to* information about the individual and *cannot be translated* back.
A SHA-256 of an MRN is derived from the individual's information by construction, and where the
identifier space is small — a hospital's MRNs are — it is trivially reversible by enumeration.
It looks like de-identification, passes review by anyone who sees "hashed", and is not
de-identification. `pseudonym()` therefore refuses to take the identifier at all.

A second thing this module does NOT claim: Safe Harbor removes the listed identifiers, and that
is a rule about fields, not a guarantee about re-identification. High-dimensional clinical data
carries quasi-identifiers that can narrow an individual down in combination. Safe Harbor is the
regulatory standard and Agent PK meets it; meeting it is not the same as the data being
unlinkable, and where the stakes warrant it the Expert Determination route at 164.514(b)(1)
is the stronger one.
"""

from __future__ import annotations

import secrets
from typing import Final

SAFE_HARBOR_IDENTIFIERS: Final[tuple[str, ...]] = (
    "names",
    "geographic_subdivisions_smaller_than_state",
    "dates_except_year_related_to_an_individual",
    "telephone_numbers",
    "fax_numbers",
    "email_addresses",
    "social_security_numbers",
    "medical_record_numbers",
    "health_plan_beneficiary_numbers",
    "account_numbers",
    "certificate_or_license_numbers",
    "vehicle_identifiers_and_serial_numbers",
    "device_identifiers_and_serial_numbers",
    "web_urls",
    "ip_addresses",
    "biometric_identifiers",
    "full_face_photographs_and_comparable_images",
    "any_other_unique_identifying_number_characteristic_or_code",
)
"""The eighteen Safe Harbor categories, named so the coverage claim is checkable.

Listed rather than merely cited because "we applied Safe Harbor" is exactly the kind of assertion
that should be inspectable. A test asserts there are eighteen of them."""

AGE_CEILING_YEARS: Final[int] = 89
"""Ages over 89, and every element of date indicating such an age, must be aggregated into a
single category. An unaggregated 94-year-old is a Safe Harbor violation on its own."""

_PSEUDONYM_BYTES: Final[int] = 16


class DeidentificationError(ValueError):
    """Raised when a record cannot be de-identified as claimed."""


def pseudonym() -> str:
    """Mint a fresh re-identification code with no relationship to the patient.

    TAKES NO ARGUMENTS, AND THAT IS THE POINT. A function that accepted the medical record number
    could hash it, and a hash of an MRN is derived from the individual's own information and
    reversible by enumeration over a small identifier space. 164.514(c) forbids exactly that. By
    taking nothing, this function cannot produce a code related to the patient even if a caller
    wanted one.

    The mapping from pseudonym back to patient, where one is kept at all, lives with the covered
    entity and never travels with the de-identified data.

    Returns:
        A random hex code.
    """
    return secrets.token_hex(_PSEUDONYM_BYTES)


def redact_age(age_years: int) -> str:
    """Age as Safe Harbor permits it to be reported.

    Args:
        age_years: The patient's age.

    Returns:
        The age as a string, or the aggregated category for anyone over 89.

    Raises:
        DeidentificationError: If the age is a bool or not a plausible age.
    """
    if isinstance(age_years, bool) or not isinstance(age_years, int):
        raise DeidentificationError("age_years must be an int")
    if age_years < 0:
        raise DeidentificationError("age_years must not be negative")
    if age_years > AGE_CEILING_YEARS:
        return f"{AGE_CEILING_YEARS}+"
    return str(age_years)


def deidentify_experience_record(
    record: dict[str, object],
    *,
    permitted_fields: frozenset[str],
) -> dict[str, object]:
    """Project an experience record down to fields cleared for a de-identified corpus.

    An ALLOWLIST, never a denylist. A denylist of the eighteen categories would pass through any
    field nobody thought of, and the field nobody thought of is the one that carries the
    identifier — the same reason the patient view enumerates its fields rather than copying them.

    Args:
        record: The experience record.
        permitted_fields: Exactly the keys allowed through.

    Returns:
        A new dict containing only permitted keys present in the record.

    Raises:
        DeidentificationError: If a permitted field name matches a Safe Harbor identifier
            category, which would mean the allowlist itself had been written wrong.
    """
    forbidden = permitted_fields & set(SAFE_HARBOR_IDENTIFIERS)
    if forbidden:
        raise DeidentificationError(
            f"the allowlist names Safe Harbor identifier categories: {sorted(forbidden)}"
        )
    return {key: value for key, value in record.items() if key in permitted_fields}


DEFAULT_TRAINING_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "hours_since_reference",
        "dose_mg",
        "dose_status",
        "concentration_ng_per_ml",
        "formulation",
        "cyp3a5_expresser",
        "weight_kg",
        "haematocrit",
        "symptom_type",
        "symptom_severity",
        "active_interactions",
        "adherence_score",
        "action_taken",
        "reward",
    }
)
"""The fields a training record may carry.

Note what is absent and why it was never a problem: **there are no dates here at all.** The PK
core has used hours-since-a-per-patient-reference-instant as its time axis since session one, for
numerical reasons rather than legal ones, and that choice happens to remove the single Safe
Harbor category that is hardest to strip from clinical time-series data. Wall-clock datetimes
exist only at the application boundary and never enter a training record.

`weight_kg` and `haematocrit` are clinical measurements, not identifiers. They are quasi-
identifiers in combination with enough else, which is the residual the module docstring declines
to wave away."""
