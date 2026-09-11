"""Compliance layer for Agent PK — consent, de-identification, audit, and the training gate.

The regulatory reasoning lives in `docs/GUARDRAILS.md`. This package is where the parts of it
that can be enforced in code are enforced, on the same principle as the channel boundary: a rule
stated in prose is a rule somebody has to remember, and a rule expressed as a function signature
is one they cannot forget.
"""

from __future__ import annotations

from datetime import datetime

from agent_pk.compliance.audit import (
    AccessPurpose,
    AccessRecord,
    AuditError,
    AuditLog,
)
from agent_pk.compliance.consent import (
    CONSENT_TEXT,
    ConsentError,
    ConsentRecord,
    ConsentScope,
    TrainingCorpus,
)
from agent_pk.compliance.deidentify import (
    AGE_CEILING_YEARS,
    DEFAULT_TRAINING_FIELDS,
    SAFE_HARBOR_IDENTIFIERS,
    DeidentificationError,
    deidentify_experience_record,
    pseudonym,
    redact_age,
)

__all__ = [
    "AGE_CEILING_YEARS",
    "CONSENT_TEXT",
    "DEFAULT_TRAINING_FIELDS",
    "SAFE_HARBOR_IDENTIFIERS",
    "AccessPurpose",
    "AccessRecord",
    "AuditError",
    "AuditLog",
    "ConsentError",
    "ConsentRecord",
    "ConsentScope",
    "DeidentificationError",
    "TrainingCorpus",
    "assemble_training_corpus",
    "deidentify_experience_record",
    "pseudonym",
    "redact_age",
]


def assemble_training_corpus(
    sources: tuple[tuple[ConsentRecord, dict[str, object]], ...],
    *,
    audit_log: AuditLog,
    actor: str,
    at: datetime,
    permitted_fields: frozenset[str] = DEFAULT_TRAINING_FIELDS,
) -> TrainingCorpus:
    """Build a training corpus from only those records whose consent permits it, de-identified.

    THIS IS THE GATE, and it is a function rather than a checklist because a checklist is
    something a future caller can skip. There is no other way to obtain a training corpus in this
    package, so a record whose patient withdrew cannot reach a model by any path that does not go
    through this refusal.

    Three things happen in a fixed order, and the order matters:

    1. **Consent is tested AT THE MOMENT OF USE**, not at the moment of collection. A patient who
       withdrew yesterday is excluded from a corpus assembled today, which is what "I can withdraw
       this consent at any time" has to mean if it means anything.
    2. **IDENTIFIED_RESEARCH is refused outright**, even when granted. That scope needs a full
       164.508 authorization or an IRB waiver, neither of which a tick box in an app can supply,
       and this product has no use for it. Refusing a granted permission is deliberate.
    3. **De-identification runs on every record that passes**, so the corpus is not PHI and the
       Privacy Rule does not reach it.

    Every inclusion and every exclusion is logged, with the exclusion reason preserved on the
    corpus itself — a corpus that silently omits the patients who withdrew is indistinguishable
    from one that never had them, and only one of those is a system working correctly.

    Args:
        sources: Consent records paired with the experience record each one governs.
        audit_log: Where the accesses are recorded.
        actor: Who is assembling the corpus.
        at: The moment of assembly. Explicit rather than defaulted, so that a corpus built for a
            past retraining can be reproduced exactly as it was permitted then.
        permitted_fields: The de-identification allowlist.

    Returns:
        A TrainingCorpus carrying the cleared records, their references, and every exclusion.
    """
    records: list[dict[str, object]] = []
    included: list[str] = []
    excluded: list[tuple[str, str]] = []

    for consent, record in sources:
        if ConsentScope.IDENTIFIED_RESEARCH in consent.granted_scopes:
            reason = (
                "identified-research scope is never honoured by this assembler; it requires a "
                "164.508 authorization or an IRB waiver, not an in-app consent"
            )
            excluded.append((consent.patient_ref, reason))
            audit_log.record_refusal(
                actor=actor,
                purpose=AccessPurpose.MODEL_TRAINING_DEIDENTIFIED,
                patient_ref=consent.patient_ref,
                reason=reason,
                at=at,
            )
            continue

        if not consent.permits(ConsentScope.DEIDENTIFIED_IMPROVEMENT, at=at):
            reason = (
                "no live consent for de-identified improvement at the time of assembly"
            )
            excluded.append((consent.patient_ref, reason))
            audit_log.record_refusal(
                actor=actor,
                purpose=AccessPurpose.MODEL_TRAINING_DEIDENTIFIED,
                patient_ref=consent.patient_ref,
                reason=reason,
                at=at,
            )
            continue

        projected = audit_log.access(
            record,
            actor=actor,
            purpose=AccessPurpose.MODEL_TRAINING_DEIDENTIFIED,
            patient_ref=consent.patient_ref,
            fields=permitted_fields,
            at=at,
        )
        records.append(
            deidentify_experience_record(projected, permitted_fields=permitted_fields)
        )
        included.append(consent.patient_ref)

    return TrainingCorpus(
        records=tuple(records),
        source_refs=tuple(included),
        excluded_refs=tuple(excluded),
    )
