"""Tests for the curated interaction loader.

The negative tests are the point. A happy-path-only suite passes against a loader that silently
drops the records it cannot parse — and a table that lost records answers "no interaction" for
every agent it lost, which is both wrong and the dangerous direction to be wrong in. Each
malformed-input test below therefore asserts that the loader RAISES, not that it copes.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from agent_pk.interactions import (
    Direction,
    InteractionsDataError,
    UnknownAgentError,
    default_data_path,
    load_table,
)


def _shipped() -> dict[str, Any]:
    """The real data file, parsed, as a mutable starting point for corruption tests."""
    data = json.loads(default_data_path().read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _write(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "interactions.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ── The shipped table ────────────────────────────────────────────────────────


def test_the_shipped_table_loads_every_section() -> None:
    table = load_table()
    # Drugs, foods and physiological events are all reportable by a patient and all must resolve.
    assert table.contains("fluconazole")
    assert table.contains("grapefruit and grapefruit juice")
    assert table.contains("diarrhoea or gastroenteritis")


def test_the_demo_case_resolves_with_its_citations() -> None:
    record = load_table().lookup("fluconazole")
    assert record.direction is Direction.RAISES
    # Both the prophylactic-dose and treatment-dose findings must come back, because the whole
    # point of the demo case is the RANGE between them.
    assert len(record.sources) == 2
    assert all(s.citation and s.url for s in record.sources)


def test_diarrhoea_raises_rather_than_lowers() -> None:
    # The counter-intuitive direction, and the one an earlier draft of the pitch got backwards.
    assert (
        load_table().lookup("diarrhoea or gastroenteritis").direction
        is Direction.RAISES
    )


def test_a_record_carries_no_magnitude_field() -> None:
    # Structural, not a spot check: the guarantee is that no magnitude can be returned at all.
    fields = {f.name for f in dataclasses.fields(load_table().lookup("fluconazole"))}
    for forbidden in (
        "magnitude",
        "fold_change",
        "factor",
        "multiplier",
        "effect_size",
    ):
        assert forbidden not in fields


def test_lookup_normalises_case_and_whitespace() -> None:
    table = load_table()
    assert table.lookup("  FLUCONAZOLE  ").agent == table.lookup("fluconazole").agent


# ── Unknown agents ───────────────────────────────────────────────────────────


def test_an_unknown_agent_raises_and_says_it_is_not_evidence_of_no_interaction() -> (
    None
):
    table = load_table()
    with pytest.raises(UnknownAgentError) as excinfo:
        table.lookup("a drug nobody has ever curated")
    # The wording is load-bearing: a caller must not read a miss as reassurance.
    assert "NOT evidence" in str(excinfo.value)


def test_a_near_miss_is_suggested_but_never_auto_selected() -> None:
    table = load_table()
    assert "fluconazole" in table.suggest("flucanazole")
    # Suggesting is a human affordance. Resolving it silently would be a wrong-drug answer.
    with pytest.raises(UnknownAgentError):
        table.lookup("flucanazole")


def test_contains_reports_absence_without_raising() -> None:
    table = load_table()
    assert table.contains("fluconazole") is True
    assert table.contains("not a real drug") is False


# ── Fail-closed loading ──────────────────────────────────────────────────────


def test_a_missing_file_raises_rather_than_yielding_an_empty_table(
    tmp_path: Path,
) -> None:
    with pytest.raises(InteractionsDataError):
        load_table(tmp_path / "absent.json")


def test_non_utf8_bytes_raise(tmp_path: Path) -> None:
    # UnicodeDecodeError subclasses ValueError, not OSError, so this needs its own branch.
    path = tmp_path / "interactions.json"
    path.write_bytes(b'{"schema_version": 1, "name": "\xff\xfe not utf-8"}')
    with pytest.raises(InteractionsDataError):
        load_table(path)


def test_malformed_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "interactions.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(InteractionsDataError):
        load_table(path)


def test_an_unrecognised_direction_raises_rather_than_skipping_the_record(
    tmp_path: Path,
) -> None:
    # THE test this module exists for. A skipped record is an agent that silently becomes
    # "no interaction". Assert the loader refuses the whole file instead.
    data = _shipped()
    data["entries"][0]["direction"] = "probably_fine"
    with pytest.raises(InteractionsDataError, match="unrecognised direction"):
        load_table(_write(tmp_path, data))


def test_a_dangling_source_id_raises(tmp_path: Path) -> None:
    data = _shipped()
    data["entries"][0]["source_ids"] = ["no_such_source"]
    with pytest.raises(InteractionsDataError, match="unknown source id"):
        load_table(_write(tmp_path, data))


def test_a_missing_required_field_raises(tmp_path: Path) -> None:
    data = _shipped()
    del data["entries"][0]["mechanism"]
    with pytest.raises(InteractionsDataError, match="mechanism"):
        load_table(_write(tmp_path, data))


def test_an_unsupported_schema_version_is_refused_by_name(tmp_path: Path) -> None:
    data = _shipped()
    data["schema_version"] = 2
    with pytest.raises(
        InteractionsDataError, match="schema_version 2 is not supported"
    ):
        load_table(_write(tmp_path, data))


def test_a_boolean_schema_version_is_refused(tmp_path: Path) -> None:
    # bool subclasses int, so `isinstance(True, int)` passes and YAML/JSON `true` would slip
    # through a naive integer check.
    data = _shipped()
    data["schema_version"] = True
    with pytest.raises(InteractionsDataError, match="must be an integer"):
        load_table(_write(tmp_path, data))


def test_a_duplicate_agent_raises_rather_than_resolving_arbitrarily(
    tmp_path: Path,
) -> None:
    data = _shipped()
    data["entries"].append(dict(data["entries"][0]))
    # The declared count is bumped so the count guard passes and the DUPLICATE check is the one
    # actually under test. Without this the count guard fires first and the test would pass for
    # the wrong reason, proving nothing about duplicate handling.
    data["expected_record_counts"]["entries"] += 1
    with pytest.raises(InteractionsDataError, match="duplicate entry"):
        load_table(_write(tmp_path, data))


def test_duplicate_source_ids_raise(tmp_path: Path) -> None:
    data = _shipped()
    data["sources"].append(dict(data["sources"][0]))
    with pytest.raises(InteractionsDataError, match="duplicate source id"):
        load_table(_write(tmp_path, data))


# ── Partial loss (adopted from Stage A, finding 1 HIGH) ──────────────────────
#
# The loader previously used `data.get(section, [])`, so a wiped or missing section loaded as an
# empty list and the table came back silently smaller. Every agent in the lost section then
# answered exactly like an agent that had never been curated. These tests pin the fix; each one
# passes against a loader that tolerates the loss, which is why they are here.


def test_a_file_with_no_sections_at_all_raises_rather_than_loading_empty(
    tmp_path: Path,
) -> None:
    # The reviewer's literal witness.
    path = _write(tmp_path, {"schema_version": 1, "sources": []})
    with pytest.raises(InteractionsDataError):
        load_table(path)


def test_a_missing_section_raises(tmp_path: Path) -> None:
    data = _shipped()
    del data["foods"]
    with pytest.raises(
        InteractionsDataError, match="required section 'foods' is missing"
    ):
        load_table(_write(tmp_path, data))


def test_an_emptied_section_raises(tmp_path: Path) -> None:
    data = _shipped()
    data["entries"] = []
    with pytest.raises(InteractionsDataError, match="is empty"):
        load_table(_write(tmp_path, data))


def test_partial_record_loss_is_caught_by_the_declared_count(tmp_path: Path) -> None:
    # Presence and non-emptiness cannot see this: the section is still there and still populated.
    data = _shipped()
    data["entries"] = data["entries"][:20]
    with pytest.raises(InteractionsDataError, match="declares"):
        load_table(_write(tmp_path, data))


def test_adding_a_record_without_updating_the_count_raises(tmp_path: Path) -> None:
    # The burden cuts both ways on purpose: growth must be declared too.
    data = _shipped()
    extra = dict(data["entries"][0])
    extra["agent"] = "a newly curated agent"
    data["entries"].append(extra)
    with pytest.raises(InteractionsDataError, match="declares"):
        load_table(_write(tmp_path, data))


def test_a_missing_count_declaration_raises(tmp_path: Path) -> None:
    data = _shipped()
    del data["expected_record_counts"]
    with pytest.raises(InteractionsDataError, match="expected_record_counts"):
        load_table(_write(tmp_path, data))


def test_an_undeclared_section_raises(tmp_path: Path) -> None:
    data = _shipped()
    del data["expected_record_counts"]["foods"]
    with pytest.raises(InteractionsDataError, match="does not declare"):
        load_table(_write(tmp_path, data))


def test_a_boolean_count_is_refused(tmp_path: Path) -> None:
    data = _shipped()
    data["expected_record_counts"]["foods"] = True
    with pytest.raises(InteractionsDataError, match="must be an integer"):
        load_table(_write(tmp_path, data))
