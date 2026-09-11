"""test_compliance.py — consent, de-identification and audit, tested as controls.

The properties here are the ones a compliance reviewer would probe, so they are asserted rather
than described: withdrawal actually excludes, a granted research scope is still refused, the
pseudonym cannot be derived from the patient, an access cannot happen without being logged, and
the log records WHICH FIELDS were read — without which nothing evidences minimum necessary.

Every patient here is synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agent_pk.compliance import (
    DEFAULT_TRAINING_FIELDS,
    SAFE_HARBOR_IDENTIFIERS,
    AccessPurpose,
    AuditError,
    AuditLog,
    ConsentError,
    ConsentRecord,
    ConsentScope,
    DeidentificationError,
    assemble_training_corpus,
    deidentify_experience_record,
    pseudonym,
    redact_age,
)

GRANTED = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
EXPIRES = GRANTED + timedelta(days=365)
NOW = datetime(2026, 9, 8, 9, 0, tzinfo=UTC)

RECORD: dict[str, object] = {
    "hours_since_reference": 696.0,
    "dose_mg": 4.0,
    "dose_status": "taken",
    "concentration_ng_per_ml": 6.4,
    "formulation": "advagraf_prolonged_release",
    "cyp3a5_expresser": None,
    "weight_kg": 71.0,
    "adherence_score": 0.96,
    # Identifiers that must never reach a corpus:
    "patient_name": "A. Patient",
    "medical_record_number": "MRN-0099122",
    "email": "someone@example.test",
    "date_of_birth": "1971-04-02",
    "home_postcode": "94110",
}


def _consent(
    ref: str = "pt-001",
    scopes: frozenset[ConsentScope] = frozenset(
        {ConsentScope.DEIDENTIFIED_IMPROVEMENT}
    ),
) -> ConsentRecord:
    return ConsentRecord(
        patient_ref=ref,
        granted_scopes=scopes,
        granted_utc=GRANTED,
        information_described="Tacrolimus levels, dosing history and symptom reports.",
        disclosed_by="Transplant centre",
        disclosed_to="Agent PK",
        purpose="Improving prediction accuracy for this patient and, de-identified, for others.",
        expires_utc=EXPIRES,
    )


# ── Consent ──────────────────────────────────────────────────────────────────


def test_a_live_consent_permits_its_granted_scope() -> None:
    assert _consent().permits(ConsentScope.DEIDENTIFIED_IMPROVEMENT, at=NOW) is True


def test_consent_does_not_leak_between_scopes() -> None:
    """Agreeing to de-identified improvement is not agreeing to identified research."""
    consent = _consent()
    assert consent.permits(ConsentScope.IDENTIFIED_RESEARCH, at=NOW) is False
    assert consent.permits(ConsentScope.OWN_CARE, at=NOW) is False


def test_withdrawal_takes_effect_from_the_moment_it_was_made() -> None:
    """ "I can withdraw at any time" has to mean the next use is excluded."""
    consent = _consent().revoked_at(NOW - timedelta(days=1))
    assert consent.permits(ConsentScope.DEIDENTIFIED_IMPROVEMENT, at=NOW) is False
    # And a use BEFORE the withdrawal was permitted, which the record must still show.
    assert (
        consent.permits(
            ConsentScope.DEIDENTIFIED_IMPROVEMENT, at=NOW - timedelta(days=5)
        )
        is True
    )


def test_withdrawal_does_not_mutate_the_original_record() -> None:
    original = _consent()
    original.revoked_at(NOW)
    assert original.revoked_utc is None


def test_an_expired_consent_stops_permitting() -> None:
    consent = _consent()
    assert consent.permits(ConsentScope.DEIDENTIFIED_IMPROVEMENT, at=EXPIRES) is False


def test_a_naive_datetime_is_refused_everywhere_it_could_hide() -> None:
    """A naive timestamp cannot be ordered against another system's, so it is not evidence."""
    with pytest.raises(ConsentError, match="timezone-aware"):
        ConsentRecord(
            patient_ref="pt-001",
            granted_scopes=frozenset({ConsentScope.OWN_CARE}),
            granted_utc=datetime(2026, 9, 1, 9, 0),  # noqa: DTZ001 — the defect under test
            information_described="x",
            disclosed_by="x",
            disclosed_to="x",
            purpose="x",
            expires_utc=EXPIRES,
        )
    with pytest.raises(ConsentError, match="timezone-aware"):
        _consent().permits(
            ConsentScope.OWN_CARE,
            at=datetime(2026, 9, 8, 9, 0),  # noqa: DTZ001 — the defect under test
        )


def test_a_consent_granting_nothing_is_refused_rather_than_stored_empty() -> None:
    with pytest.raises(ConsentError, match="permits nothing"):
        _consent(scopes=frozenset())


def test_required_elements_cannot_be_blank() -> None:
    with pytest.raises(ConsentError, match="required element"):
        ConsentRecord(
            patient_ref="pt-001",
            granted_scopes=frozenset({ConsentScope.OWN_CARE}),
            granted_utc=GRANTED,
            information_described="   ",
            disclosed_by="x",
            disclosed_to="x",
            purpose="x",
            expires_utc=EXPIRES,
        )


# ── De-identification ────────────────────────────────────────────────────────


def test_there_are_eighteen_safe_harbor_categories() -> None:
    assert len(SAFE_HARBOR_IDENTIFIERS) == 18
    assert len(set(SAFE_HARBOR_IDENTIFIERS)) == 18


def test_the_pseudonym_cannot_be_derived_from_the_patient() -> None:
    """The mistake this prevents: a hash of the MRN is not a compliant pseudonym.

    164.514(c) permits a re-identification code only if it is not derived from information about
    the individual. `pseudonym()` takes no arguments, so a caller holding an MRN cannot pass it
    in even by mistake — and two calls never collide.
    """
    with pytest.raises(TypeError):
        pseudonym("MRN-0099122")  # type: ignore[call-arg]
    assert pseudonym() != pseudonym()
    assert len(pseudonym()) == 32


def test_ages_over_eighty_nine_are_aggregated() -> None:
    assert redact_age(64) == "64"
    assert redact_age(89) == "89"
    assert redact_age(90) == "89+"
    assert redact_age(103) == "89+"


def test_redact_age_refuses_a_bool() -> None:
    """bool subclasses int, so True would otherwise pass every numeric check as age 1."""
    with pytest.raises(DeidentificationError):
        redact_age(True)  # type: ignore[arg-type]


def test_deidentification_is_an_allowlist_not_a_denylist() -> None:
    """A denylist passes through the field nobody thought of, which is the one that identifies."""
    cleaned = deidentify_experience_record(
        RECORD, permitted_fields=DEFAULT_TRAINING_FIELDS
    )
    for identifier in (
        "patient_name",
        "medical_record_number",
        "email",
        "date_of_birth",
        "home_postcode",
    ):
        assert identifier not in cleaned
    assert cleaned["concentration_ng_per_ml"] == 6.4
    assert set(cleaned) <= DEFAULT_TRAINING_FIELDS


def test_the_training_allowlist_carries_no_dates() -> None:
    """Dates are the Safe Harbor category hardest to strip from a clinical time series.

    The PK core has used hours-since-a-per-patient-reference-instant since session one, for
    numerical reasons. This test pins the legal consequence of that choice so a later change to
    wall-clock timestamps has to confront it.
    """
    for name in DEFAULT_TRAINING_FIELDS:
        assert "date" not in name and "timestamp" not in name, (
            f"{name} looks like a date field in a corpus that must carry none"
        )


def test_an_allowlist_naming_an_identifier_category_is_refused() -> None:
    with pytest.raises(
        DeidentificationError, match="Safe Harbor identifier categories"
    ):
        deidentify_experience_record(
            RECORD, permitted_fields=frozenset({"email_addresses"})
        )


# ── Audit ────────────────────────────────────────────────────────────────────


def test_reading_is_logging_and_returns_only_the_declared_fields() -> None:
    log = AuditLog()
    got = log.access(
        RECORD,
        actor="dr-nnn",
        purpose=AccessPurpose.TREATMENT,
        patient_ref="pt-001",
        fields=frozenset({"concentration_ng_per_ml"}),
        at=NOW,
    )
    assert got == {"concentration_ng_per_ml": 6.4}
    assert "medical_record_number" not in got
    assert len(log) == 1
    entry = next(iter(log))
    assert entry.fields_accessed == ("concentration_ng_per_ml",)
    assert entry.purpose is AccessPurpose.TREATMENT
    assert entry.timestamp_utc.tzinfo is not None


def test_the_log_records_which_fields_were_read() -> None:
    """Without this, nothing in the log evidences minimum necessary."""
    log = AuditLog()
    log.access(
        RECORD,
        actor="dr-nnn",
        purpose=AccessPurpose.TREATMENT,
        patient_ref="pt-001",
        fields=frozenset({"concentration_ng_per_ml", "dose_mg"}),
        at=NOW,
    )
    assert next(iter(log)).fields_accessed == ("concentration_ng_per_ml", "dose_mg")


def test_an_access_declaring_nothing_is_refused() -> None:
    log = AuditLog()
    with pytest.raises(AuditError, match="minimum necessary"):
        log.access(
            RECORD,
            actor="dr-nnn",
            purpose=AccessPurpose.TREATMENT,
            patient_ref="pt-001",
            fields=frozenset(),
            at=NOW,
        )


def test_refusals_are_logged_too() -> None:
    """A log of only successful reads cannot show that refusals happen at all."""
    log = AuditLog()
    log.record_refusal(
        actor="dr-nnn",
        purpose=AccessPurpose.MODEL_TRAINING_DEIDENTIFIED,
        patient_ref="pt-002",
        reason="consent withdrawn",
        at=NOW,
    )
    entry = next(iter(log))
    assert entry.outcome.startswith("refused:")
    assert entry.fields_accessed == ()


def test_the_log_cannot_be_edited_through_iteration() -> None:
    log = AuditLog()
    log.access(
        RECORD,
        actor="a",
        purpose=AccessPurpose.TREATMENT,
        patient_ref="pt-001",
        fields=frozenset({"dose_mg"}),
        at=NOW,
    )
    entries = list(log)
    entries.clear()
    assert len(log) == 1


# ── The training gate ────────────────────────────────────────────────────────


def test_a_withdrawn_patient_does_not_reach_the_corpus() -> None:
    log = AuditLog()
    withdrawn = _consent("pt-002").revoked_at(NOW - timedelta(days=1))
    corpus = assemble_training_corpus(
        ((_consent("pt-001"), RECORD), (withdrawn, RECORD)),
        audit_log=log,
        actor="trainer",
        at=NOW,
    )
    assert corpus.source_refs == ("pt-001",)
    assert len(corpus.records) == 1
    assert [ref for ref, _ in corpus.excluded_refs] == ["pt-002"]


def test_exclusions_are_carried_not_dropped() -> None:
    """A corpus that silently omits withdrawals looks like one that never had them."""
    log = AuditLog()
    corpus = assemble_training_corpus(
        ((_consent("pt-002").revoked_at(NOW - timedelta(days=1)), RECORD),),
        audit_log=log,
        actor="trainer",
        at=NOW,
    )
    assert corpus.records == ()
    assert len(corpus.excluded_refs) == 1
    assert "no live consent" in corpus.excluded_refs[0][1]


def test_identified_research_is_refused_even_when_granted() -> None:
    """A tick box cannot supply a 164.508 authorization, so this scope is never honoured."""
    log = AuditLog()
    over_granted = _consent(
        "pt-003",
        frozenset(
            {ConsentScope.DEIDENTIFIED_IMPROVEMENT, ConsentScope.IDENTIFIED_RESEARCH}
        ),
    )
    corpus = assemble_training_corpus(
        ((over_granted, RECORD),), audit_log=log, actor="trainer", at=NOW
    )
    assert corpus.records == ()
    assert "164.508" in corpus.excluded_refs[0][1]


def test_the_corpus_carries_no_identifiers() -> None:
    log = AuditLog()
    corpus = assemble_training_corpus(
        ((_consent("pt-001"), RECORD),), audit_log=log, actor="trainer", at=NOW
    )
    for record in corpus.records:
        for identifier in (
            "patient_name",
            "medical_record_number",
            "email",
            "date_of_birth",
        ):
            assert identifier not in record


def test_every_inclusion_and_exclusion_is_audited() -> None:
    log = AuditLog()
    assemble_training_corpus(
        (
            (_consent("pt-001"), RECORD),
            (_consent("pt-002").revoked_at(NOW - timedelta(days=1)), RECORD),
        ),
        audit_log=log,
        actor="trainer",
        at=NOW,
    )
    assert len(log) == 2
    refs = {entry.patient_ref for entry in log}
    assert refs == {"pt-001", "pt-002"}
    for entry in log:
        assert entry.purpose is AccessPurpose.MODEL_TRAINING_DEIDENTIFIED


def test_consent_is_tested_at_the_moment_of_use_not_of_collection() -> None:
    """A corpus rebuilt for a past retraining must reproduce what was permitted THEN."""
    log = AuditLog()
    withdrawn_today = _consent("pt-004").revoked_at(NOW)
    past = assemble_training_corpus(
        ((withdrawn_today, RECORD),),
        audit_log=log,
        actor="trainer",
        at=NOW - timedelta(days=30),
    )
    present = assemble_training_corpus(
        ((withdrawn_today, RECORD),), audit_log=log, actor="trainer", at=NOW
    )
    assert past.source_refs == ("pt-004",)
    assert present.source_refs == ()
