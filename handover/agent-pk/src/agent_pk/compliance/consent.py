"""consent.py — what the patient actually agreed to, and what that permits.

A checkbox is not an authorization. The Privacy Rule sets out required elements for a valid
authorization (45 CFR 164.508(c)) — the information described, who discloses it, who receives it,
the purpose, an expiration date or event, the right to revoke and how, a statement about
redisclosure, and a signature with a date. A single line of agreement carries almost none of
them, and published analysis is blunt that a general consent to "research and quality
improvement" almost certainly does not satisfy HIPAA's authorization requirements for commercial
AI training.

So this module does not pretend one tick box clears three regimes. It does three separable things:

1. **Records consent as a structured object** carrying the 164.508(c) elements, so what was
   agreed is inspectable rather than implied.
2. **Separates the scopes**, because they are legally different acts. Using a patient's data to
   care for that patient is treatment and health care operations. Using it to build something
   that helps OTHER patients is generalizable knowledge, which is research.
3. **Makes an ungranted use unrepresentable**, the same way the channel boundary does. A training
   corpus cannot be assembled from records whose consent does not permit it, because the function
   that assembles one takes the consent and filters.

**THE SIMPLIFICATION THAT DOES MOST OF THE WORK IS NOT CONSENT AT ALL — IT IS
DE-IDENTIFICATION.** Once data is de-identified under 45 CFR 164.514(b), it is no longer protected
health information, the Privacy Rule stops applying to it, and neither individual authorization
nor IRB approval is required to use it. Agent PK de-identifies before any model training, which
removes the authorization question from the training path entirely. The consent recorded here is
then a matter of transparency and of the patient's own control — which is worth having on its own
terms — rather than the legal mechanism the training rests on. See `deidentify.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class ConsentError(ValueError):
    """Raised when an action is attempted that the recorded consent does not permit."""


class ConsentScope(StrEnum):
    """The separable things a patient may agree to, kept apart because the law keeps them apart.

    OWN_CARE is treatment and health care operations: using this patient's data to look after
    this patient. It is what makes the product function at all.

    DEIDENTIFIED_IMPROVEMENT covers model training on data from which the Safe Harbor identifiers
    have been removed. Because de-identified data is not PHI, this scope is not a HIPAA
    authorization and does not need to be — it is recorded so the patient has a say, and so the
    say is revocable.

    IDENTIFIED_RESEARCH is the strict path: identifiable data used to develop generalizable
    knowledge. That IS research under 45 CFR 164.501, and it needs a full authorization or an
    IRB/Privacy Board waiver under 164.512(i). Agent PK does not use it, and the training
    assembler refuses it outright, but it exists in this enum so that a future use cannot quietly
    borrow one of the weaker scopes to do it.
    """

    OWN_CARE = "own_care"
    DEIDENTIFIED_IMPROVEMENT = "deidentified_improvement"
    IDENTIFIED_RESEARCH = "identified_research"


CONSENT_TEXT: dict[ConsentScope, str] = {
    ConsentScope.OWN_CARE: (
        "I agree that my tacrolimus levels, dosing history and symptom reports can be used by "
        "this assistant to follow my own treatment and to inform my transplant team."
    ),
    ConsentScope.DEIDENTIFIED_IMPROVEMENT: (
        "I consent to my tacrolimus levels, dosing history and symptom reports being used to "
        "improve the prediction accuracy of this assistant for me and for other patients "
        "(de-identified). I understand I can withdraw this consent at any time."
    ),
    ConsentScope.IDENTIFIED_RESEARCH: (
        "I authorise my identifiable health information to be used for research. This requires "
        "a separate written authorisation and is not granted by any tick box in this app."
    ),
}
"""The words the patient is shown, kept beside the scope they grant.

The DEIDENTIFIED_IMPROVEMENT wording is the operator's own. It is good, plain, and revocable, and
its two halves happen to track the legal line exactly: "for me" is health care operations, "for
other patients" is generalizable knowledge. What it is NOT is a HIPAA authorization — it carries
none of the 164.508(c) elements — and the product does not need it to be one, because the training
path is de-identified. Saying it "covers IRB, HIPAA and FTC requirements" would be wrong, and
wrong in the direction that a compliance reviewer would find in a minute."""


@dataclass(frozen=True, slots=True)
class ConsentRecord:
    """One patient's recorded consent, with the elements that make it inspectable.

    Attributes:
        patient_ref: The pseudonymous reference this consent attaches to.
        granted_scopes: What the patient agreed to, at the moment of signing.
        granted_utc: When. Timezone-aware UTC, always.
        information_described: What data the consent covers, in the patient's own terms.
        disclosed_by: Who holds and discloses the data.
        disclosed_to: Who receives it.
        purpose: Why.
        expires_utc: When the consent lapses if not renewed. An authorization with no expiry is
            not a valid one, and an open-ended permission is not something a patient can weigh.
        revoked_utc: Set when the patient withdraws. Revocation is recorded, never erased, so
            that what was permitted at the time of a past use stays auditable.
        redisclosure_note: The statement that information disclosed onward may no longer be
            protected by the Privacy Rule.
    """

    patient_ref: str
    granted_scopes: frozenset[ConsentScope]
    granted_utc: datetime
    information_described: str
    disclosed_by: str
    disclosed_to: str
    purpose: str
    expires_utc: datetime
    revoked_utc: datetime | None = None
    redisclosure_note: str = (
        "Information disclosed under this consent may be redisclosed by the recipient and may "
        "then no longer be protected by the HIPAA Privacy Rule."
    )

    def __post_init__(self) -> None:
        for name, value in (
            ("granted_utc", self.granted_utc),
            ("expires_utc", self.expires_utc),
        ):
            if value.tzinfo is None:
                raise ConsentError(
                    f"{name} must be timezone-aware UTC — a naive datetime on a consent record "
                    f"cannot be compared across systems and is how an expired consent reads as live"
                )
        if self.revoked_utc is not None and self.revoked_utc.tzinfo is None:
            raise ConsentError("revoked_utc must be timezone-aware UTC")
        if self.expires_utc <= self.granted_utc:
            raise ConsentError("expires_utc must be after granted_utc")
        if not self.patient_ref:
            raise ConsentError("patient_ref must not be empty")
        for name, text in (
            ("information_described", self.information_described),
            ("disclosed_by", self.disclosed_by),
            ("disclosed_to", self.disclosed_to),
            ("purpose", self.purpose),
        ):
            if not text.strip():
                raise ConsentError(
                    f"{name} must not be empty — it is a required element"
                )
        if not self.granted_scopes:
            raise ConsentError(
                "a consent record with no scopes permits nothing; record the refusal explicitly "
                "rather than storing an empty consent"
            )

    def permits(self, scope: ConsentScope, *, at: datetime | None = None) -> bool:
        """Whether this consent permits a scope at a moment in time.

        Args:
            scope: The scope being tested.
            at: The moment to test. Defaults to now. Passing the moment explicitly is what makes
                a past use auditable: the question is never "may we do this" but "was this
                permitted when it happened".

        Returns:
            True only if the scope was granted, the consent had not expired, and it had not been
            revoked at that moment.

        Raises:
            ConsentError: If `at` is a naive datetime.
        """
        moment = at if at is not None else datetime.now(UTC)
        if moment.tzinfo is None:
            raise ConsentError("`at` must be timezone-aware UTC")
        if scope not in self.granted_scopes:
            return False
        if moment >= self.expires_utc:
            return False
        return not (self.revoked_utc is not None and moment >= self.revoked_utc)

    def revoked_at(self, when: datetime) -> ConsentRecord:
        """A copy of this consent marked revoked. The original is never mutated.

        Withdrawal must be as easy as granting, and it must not destroy the record of what was
        permitted before — a use that was lawful when it happened does not become unlawful
        retrospectively, and the audit trail has to be able to say so.
        """
        if when.tzinfo is None:
            raise ConsentError("revocation time must be timezone-aware UTC")
        return ConsentRecord(
            patient_ref=self.patient_ref,
            granted_scopes=self.granted_scopes,
            granted_utc=self.granted_utc,
            information_described=self.information_described,
            disclosed_by=self.disclosed_by,
            disclosed_to=self.disclosed_to,
            purpose=self.purpose,
            expires_utc=self.expires_utc,
            revoked_utc=when,
            redisclosure_note=self.redisclosure_note,
        )


@dataclass(frozen=True, slots=True)
class TrainingCorpus:
    """Records cleared for model training, with the reason each one was cleared.

    Attributes:
        records: The de-identified records.
        source_refs: The pseudonymous references they came from, for audit.
        excluded_refs: References deliberately left out, and why. Carried rather than dropped:
            a corpus that silently omits the patients who withdrew looks identical to one that
            never had them, and only one of those is a system working correctly.
    """

    records: tuple[dict[str, object], ...] = field(default_factory=tuple)
    source_refs: tuple[str, ...] = field(default_factory=tuple)
    excluded_refs: tuple[tuple[str, str], ...] = field(default_factory=tuple)
