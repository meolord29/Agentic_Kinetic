"""audit.py — every access to patient data, with who, when, why, and exactly what.

Two obligations meet in one record. The Security Rule requires audit controls that record and
examine activity in systems holding protected health information (45 CFR 164.312(b)), and the
Privacy Rule's minimum necessary standard (164.502(b), 164.514(d)) requires that a use be limited
to the information reasonably needed for its purpose. Logging WHO and WHEN satisfies neither on
its own: a log that does not record WHICH FIELDS were read cannot evidence minimum necessary,
because nothing in it distinguishes reading a trough from reading the whole chart.

So an access here is not a permission that is then logged. **The access IS the projection**:
`access()` takes the fields the caller declares it needs, returns only those, and writes the
record in the same call. A caller cannot read more than it declared, because it never receives
more than it declared, and it cannot read without logging, because the read is the log.

The log is APPEND-ONLY in its interface. Nothing here edits or deletes an entry, and an
in-memory log is the demo's substrate rather than a claim about production storage — see the
honest limits at the foot of this docstring.

HONEST LIMITS, because an audit control that overstates itself is worse than none:
  * This is an in-process, in-memory log. It provides no tamper-evidence, no signing, and no
    durability. A production deployment needs append-only storage with integrity protection;
    the interface here is shaped so that swapping the sink does not change any caller.
  * It records what the application did. It cannot record what someone did around the
    application — direct database access, a backup copy, a screenshot.
  * `actor` is whatever the caller says it is. This module does not authenticate anyone.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class AuditError(ValueError):
    """Raised when an access cannot be recorded as described."""


class AccessPurpose(StrEnum):
    """Why the data was touched. A closed set, because "purpose" as free text is unauditable.

    These track the Privacy Rule's own categories rather than an invented taxonomy: treatment,
    payment and health care operations are the permitted uses that need no authorization, and the
    remainder are the ones that do — which is precisely the distinction an auditor is looking for.
    """

    TREATMENT = "treatment"
    HEALTH_CARE_OPERATIONS = "health_care_operations"
    PATIENT_ACCESS = "patient_access"
    MODEL_TRAINING_DEIDENTIFIED = "model_training_deidentified"
    REQUIRED_BY_LAW = "required_by_law"


@dataclass(frozen=True, slots=True)
class AccessRecord:
    """One logged access to patient data.

    Attributes:
        timestamp_utc: When. Timezone-aware UTC, always — a naive timestamp in an audit log is
            not evidence of anything, because it cannot be ordered against another system's.
        actor: Who performed the access, as the application understands them.
        purpose: Why, from the closed set.
        patient_ref: Whose data, pseudonymously.
        fields_accessed: EXACTLY which fields were returned. This is the minimum-necessary
            evidence, and it is the field that makes the record worth keeping.
        outcome: Whether the access succeeded or was refused. Refusals are logged too: a denied
            access is often the more interesting entry.
    """

    timestamp_utc: datetime
    actor: str
    purpose: AccessPurpose
    patient_ref: str
    fields_accessed: tuple[str, ...]
    outcome: str = "granted"

    def __post_init__(self) -> None:
        if self.timestamp_utc.tzinfo is None:
            raise AuditError("timestamp_utc must be timezone-aware UTC")
        if not self.actor.strip():
            raise AuditError("actor must not be empty")
        if not self.patient_ref.strip():
            raise AuditError("patient_ref must not be empty")
        if not isinstance(self.purpose, AccessPurpose):
            raise AuditError("purpose must be an AccessPurpose member")


class AuditLog:
    """An append-only record of accesses, and the gate through which data is read.

    Deliberately NOT a list somebody remembers to append to. The only way to read patient data
    through this module is `access()`, which logs as it reads.
    """

    def __init__(self) -> None:
        self._entries: list[AccessRecord] = []

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[AccessRecord]:
        """Iterate the entries. Yields copies of an immutable type; the log cannot be edited."""
        return iter(tuple(self._entries))

    def access(
        self,
        record: Mapping[str, object],
        *,
        actor: str,
        purpose: AccessPurpose,
        patient_ref: str,
        fields: frozenset[str],
        at: datetime | None = None,
    ) -> dict[str, object]:
        """Read the declared fields of a patient record, logging the access in the same act.

        Args:
            record: The full patient record.
            actor: Who is reading.
            purpose: Why, from the closed set.
            patient_ref: Pseudonymous patient reference.
            fields: EXACTLY the fields needed for this purpose. Anything else is not returned.
            at: The moment of access. Defaults to now.

        Returns:
            A new dict containing only the requested fields that exist in the record.

        Raises:
            AuditError: If no fields are declared. A read of nothing is either a mistake or an
                attempt to touch a record without saying what was touched; both should surface.
        """
        if not fields:
            raise AuditError(
                "an access must declare the fields it needs — minimum necessary cannot be "
                "evidenced by a record that does not say what was read"
            )
        moment = at if at is not None else datetime.now(UTC)
        projected = {key: value for key, value in record.items() if key in fields}
        self._entries.append(
            AccessRecord(
                timestamp_utc=moment,
                actor=actor,
                purpose=purpose,
                patient_ref=patient_ref,
                fields_accessed=tuple(sorted(projected)),
            )
        )
        return projected

    def record_refusal(
        self,
        *,
        actor: str,
        purpose: AccessPurpose,
        patient_ref: str,
        reason: str,
        at: datetime | None = None,
    ) -> None:
        """Log an access that was refused.

        A refusal is an audit event in its own right. A log containing only successful reads
        cannot distinguish a system that was never attacked from one whose refusals go unrecorded.
        """
        if not reason.strip():
            raise AuditError("a refusal must carry a reason")
        moment = at if at is not None else datetime.now(UTC)
        self._entries.append(
            AccessRecord(
                timestamp_utc=moment,
                actor=actor,
                purpose=purpose,
                patient_ref=patient_ref,
                fields_accessed=(),
                outcome=f"refused: {reason}",
            )
        )

    def entries_for(self, patient_ref: str) -> tuple[AccessRecord, ...]:
        """Every logged access for one patient — the accounting a patient may ask for."""
        return tuple(e for e in self._entries if e.patient_ref == patient_ref)
