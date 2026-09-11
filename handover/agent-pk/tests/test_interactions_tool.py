"""Tests for the agent-facing interaction tool.

The tool boundary is where three safety properties either survive or die, and each of these
tests exists because the property has already been lost at a boundary somewhere in this project:

1. An unknown agent must be an ANSWER, not an exception — a raising tool invites a language
   model to answer from its own weights instead.
2. The "absence is not evidence of no interaction" statement must be a FIELD of the result. It
   lives in an exception message in the loader, and an exception that is caught is discarded.
3. A direction token must never travel without its plain-English meaning, because `raises` on
   `diarrhoea` is the counterintuitive answer and the bare token is what gets inverted.

A happy-path suite passes against a tool that loses all three.
"""

from __future__ import annotations

import json

import pytest

from agent_pk.interactions import (
    ABSENCE_IS_NOT_EVIDENCE,
    NO_EXACT_MATCH_BUT_CANDIDATES,
    SIMILARLY_SPELLED_POSSIBLY_DIFFERENT,
    DIRECTION_MEANING,
    Direction,
    InteractionLookupResult,
    UnknownAgentError,
    default_data_path,
    load_table,
    lookup_interaction,
    lookup_interaction_json,
)


# ── The unknown agent is an answer, not an exception ─────────────────────────


def test_unknown_agent_returns_a_result_rather_than_raising() -> None:
    """The property the whole module exists for.

    `InteractionTable.lookup` raises for an unknown agent, which is correct for a Python
    caller. If that exception reached a language model the model would retry or fill the gap
    itself, and the gap is a drug-interaction claim.
    """
    result = lookup_interaction("a drug that is definitely not in this table")
    assert isinstance(result, InteractionLookupResult)
    assert result.found is False


def test_the_underlying_loader_still_raises() -> None:
    """The tool's softening must not have softened the loader.

    If this ever fails, the not-found conversion has been pushed down into the loader, where
    Python callers would silently receive an empty record instead of an error.
    """
    table = load_table()
    with pytest.raises(UnknownAgentError):
        table.lookup("a drug that is definitely not in this table")


def test_not_found_carries_the_absence_is_not_evidence_statement() -> None:
    """`found: false` on its own reads as "no interaction" to almost any reader.

    The statement must be IN the payload, not in a log line or a docstring.
    """
    result = lookup_interaction("nonexistent agent xyzzy")
    assert ABSENCE_IS_NOT_EVIDENCE in result.guidance
    assert "not evidence" in result.guidance.lower()
    assert "unknown" in result.guidance.lower()


def test_not_found_offers_suggestions_but_does_not_resolve_them() -> None:
    """A near-miss onto the wrong drug is worse than no answer.

    A close typo must produce a NOT-FOUND result that names candidates for a human, never a
    found result for the drug the tool guessed at.
    """
    table = load_table()
    real_name = table.records[0].agent
    typo = real_name[:-1] + "z" if len(real_name) > 3 else real_name + "zz"

    result = lookup_interaction(typo)
    assert result.found is False
    assert result.direction is None
    assert result.agent is None


# ── A direction never travels without its meaning ────────────────────────────


def test_every_direction_member_has_a_meaning() -> None:
    """Import-time check, asserted again here so the reason is discoverable from the tests."""
    for direction in Direction:
        assert direction in DIRECTION_MEANING
        assert DIRECTION_MEANING[direction].strip()


def test_found_result_carries_direction_and_its_meaning_together() -> None:
    """The token alone is what gets inverted; the sentence is what a model repeats."""
    table = load_table()
    for record in table.records:
        result = lookup_interaction(record.agent)
        assert result.found is True
        assert result.direction == record.direction.value
        assert result.direction_meaning == DIRECTION_MEANING[record.direction]


def test_raises_meaning_says_the_level_goes_up() -> None:
    """The counterintuitive case, stated explicitly.

    Diarrhoea RAISES tacrolimus by damaging the gut wall that normally metabolises it, which
    reads backwards to anyone reasoning from "illness lowers things". The meaning sentence has
    to say UP in words, not leave it to be inferred from the token.
    """
    meaning = DIRECTION_MEANING[Direction.RAISES]
    assert "UP" in meaning
    assert DIRECTION_MEANING[Direction.LOWERS] != meaning
    assert "DOWN" in DIRECTION_MEANING[Direction.LOWERS]


# ── Every result constrains magnitude ────────────────────────────────────────


@pytest.mark.parametrize("agent", ["nonexistent agent xyzzy", None])
def test_every_result_forbids_inventing_a_magnitude(agent: str | None) -> None:
    """There is no magnitude field in the source data by design.

    A model handed a direction and a mechanism with no instruction against it will readily
    supply a plausible magnitude, and a fabricated magnitude here is a dosing claim.
    """
    name = agent if agent is not None else load_table().records[0].agent
    result = lookup_interaction(name)
    assert "never state or imply a magnitude" in result.guidance.lower() or (
        "magnitude" in result.guidance.lower()
    )
    assert "does not adjust a dose" in result.guidance


# ── Citations survive the boundary ───────────────────────────────────────────


def test_citations_are_carried_for_every_record_that_has_them() -> None:
    """A directional claim without its source is not reviewable."""
    table = load_table()
    checked = 0
    for record in table.records:
        if not record.sources:
            continue
        result = lookup_interaction(record.agent)
        assert len(result.sources) == len(record.sources)
        for projected, original in zip(result.sources, record.sources, strict=True):
            assert projected.citation == original.citation
            assert projected.url == original.url
        checked += 1
    assert checked > 0, "the fixture has no cited records, so this test proved nothing"


# ── The JSON boundary ────────────────────────────────────────────────────────


def test_json_form_round_trips_through_the_encoder() -> None:
    """A frozen dataclass or a StrEnum member does not serialise reliably.

    Most tool decorators serialise the return value, so a type that survives in-process and
    fails at the boundary would surface only at runtime, inside the agent.
    """
    table = load_table()
    for name in (table.records[0].agent, "nonexistent agent xyzzy"):
        payload = lookup_interaction_json(name)
        encoded = json.dumps(payload)
        assert json.loads(encoded) == payload


def test_json_form_contains_no_enum_members() -> None:
    """`direction` must be the plain string value, not a StrEnum instance."""
    table = load_table()
    payload = lookup_interaction_json(table.records[0].agent)
    assert type(payload["direction"]) is str


def test_queried_echoes_the_input_not_the_table_spelling() -> None:
    """So a model can say what it searched for, rather than silently substituting."""
    table = load_table()
    shouted = table.records[0].agent.upper()
    result = lookup_interaction(shouted)
    assert result.queried == shouted
    assert result.agent == table.records[0].agent


# ── Input validation ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", ["", "   ", None, 3])
def test_empty_or_non_string_agent_is_refused(bad: object) -> None:
    """An empty query must not be answered as though it were a real lookup."""
    with pytest.raises(ValueError):
        lookup_interaction(bad)  # type: ignore[arg-type]


def test_explicit_data_path_bypasses_the_module_cache() -> None:
    """The tests need a fresh load; the cache is for the packaged default only."""
    result = lookup_interaction(
        load_table().records[0].agent, data_path=default_data_path()
    )
    assert result.found is True


# ── Short-form queries, and the two shapes of not-found ─────────────────────
#
# MEASURED s9, then CORRECTED after an adversarial review raised it as a HIGH.
#
# The table names its food and event entries as full descriptive phrases ("diarrhoea or
# gastroenteritis", "grapefruit and grapefruit juice") while matching is exact, so a patient's
# short form missed. The first version of this module treated that as a known gap and pinned it.
# The review's finding was sharper and correct: the result did not merely fail to help, it
# ASSERTED that the agent was not in the curated table — which is FALSE when the table holds it —
# and then wrapped the false claim in a disclaimer that made it read as careful.
#
# The fix does NOT relax matching. `lookup` still resolves nothing fuzzily, `found` stays False,
# and a near miss onto the wrong DRUG remains impossible. What changed is that a miss now offers
# deterministic token-containment candidates for a HUMAN to choose between, and only a miss with
# NO candidates may claim absence.

SHORT_FORMS_THAT_SURFACE_THE_RIGHT_ENTRY = (
    ("diarrhoea", "diarrhoea or gastroenteritis"),
    ("gastroenteritis", "diarrhoea or gastroenteritis"),
    ("grapefruit", "grapefruit and grapefruit juice"),
    ("grapefruit juice", "grapefruit and grapefruit juice"),
    ("star fruit", "star fruit (carambola)"),
    ("carambola", "star fruit (carambola)"),
    ("vomiting", "vomiting within one hour of a dose"),
    ("potassium", "potassium supplements"),
    ("haematocrit", "changing haematocrit"),
)


@pytest.mark.parametrize(
    ("short_form", "table_name"), SHORT_FORMS_THAT_SURFACE_THE_RIGHT_ENTRY
)
def test_a_short_form_offers_the_entry_without_resolving_it(
    short_form: str, table_name: str
) -> None:
    """The candidate is offered for a person to confirm — never selected automatically."""
    table = load_table()
    assert table.contains(table_name), (
        f"{table_name!r} is no longer in the table, so this test is measuring nothing"
    )
    result = lookup_interaction(short_form)
    assert result.found is False, "a short form must not silently resolve to an entry"
    assert result.direction is None
    assert table_name in result.suggestions


@pytest.mark.parametrize(
    ("short_form", "_table_name"), SHORT_FORMS_THAT_SURFACE_THE_RIGHT_ENTRY
)
def test_a_short_form_never_claims_the_agent_is_absent(
    short_form: str, _table_name: str
) -> None:
    """The finding this test exists for.

    Claiming absence for an agent the table HOLDS is a false statement about a clinical safety
    table. The candidate branch must not use the absence text.
    """
    result = lookup_interaction(short_form)
    assert ABSENCE_IS_NOT_EVIDENCE not in result.guidance
    assert NO_EXACT_MATCH_BUT_CANDIDATES in result.guidance


def test_a_genuinely_absent_agent_still_claims_absence() -> None:
    """The other half. Softening the absence claim everywhere would be the opposite defect."""
    result = lookup_interaction("zzzz definitely not a real agent")
    assert result.found is False
    assert result.suggestions == ()
    assert ABSENCE_IS_NOT_EVIDENCE in result.guidance


def test_a_brand_name_is_absent_and_says_so() -> None:
    """A KNOWN REMAINING LIMIT, asserted rather than described.

    "Advil" is ibuprofen and the table holds ibuprofen, but no token is shared, so containment
    cannot reach it and MUST NOT — a brand-to-generic mapping is curated data, not something to
    infer here. The honest behaviour is the absence claim plus the disclaimer, and that is what
    this pins. It inverts when an alias field is added to the data.
    """
    result = lookup_interaction("Advil")
    assert result.found is False
    assert result.suggestions == ()
    assert ABSENCE_IS_NOT_EVIDENCE in result.guidance


def test_containment_alone_never_pairs_two_different_drugs() -> None:
    """The safety property containment buys, tested on the RULE rather than on the union.

    Containment matches WHOLE WORDS, so it cannot cross between two drugs whose names merely
    look alike — which is why it is admissible where edit distance would not be. Asserted
    across every pair in the table, so it holds by construction rather than on the examples
    someone thought to pick.
    """
    from agent_pk.interactions.tool import _tokens

    names = [r.agent for r in load_table().records]
    for i, first in enumerate(names):
        for second in names[i + 1 :]:
            a, b = _tokens(first), _tokens(second)
            if a <= b or b <= a:
                assert a & b, (
                    f"containment paired {first!r} with {second!r} sharing no whole word"
                )


def test_an_edit_distance_only_hit_is_labelled_as_a_possible_different_drug() -> None:
    """ADOPTED FROM A DECORRELATED SECOND-LINEAGE REVIEW (s9, Stage B, MEDIUM).

    The first reviewer rated this LOW; the second argued it up and was right. "nimodipine" is
    not in the table, "nifedipine" is, and they are DIFFERENT DRUGS that containment cannot
    pair — only edit distance reaches across. Telling the model the table holds a "closely
    related" entry the agent "may well BE in" is a false statement about a clinical table, and
    the warm label is what makes "did you mean nifedipine?" the natural next turn.

    The name is still shown, because a person spotting their own typo is the legitimate use.
    What changed is what the software CLAIMS about it.
    """
    result = lookup_interaction("nimodipine")
    assert result.found is False
    assert result.direction is None
    assert result.direction_meaning is None
    assert "nifedipine" in result.suggestions
    assert SIMILARLY_SPELLED_POSSIBLY_DIFFERENT in result.guidance
    assert NO_EXACT_MATCH_BUT_CANDIDATES not in result.guidance
    assert ABSENCE_IS_NOT_EVIDENCE not in result.guidance


def test_the_typo_branch_forbids_the_model_from_looking_one_up() -> None:
    """The instruction has to be explicit, because the helpful move here is the unsafe one."""
    guidance = lookup_interaction("nimodipine").guidance
    assert "may be entirely" in guidance
    assert "DIFFERENT" in guidance
    assert "do NOT look one up" in guidance


def test_the_three_not_found_shapes_are_mutually_exclusive() -> None:
    """Exactly one claim may be made, and it must be the one the evidence supports."""
    cases = {
        "grapefruit": NO_EXACT_MATCH_BUT_CANDIDATES,
        "nimodipine": SIMILARLY_SPELLED_POSSIBLY_DIFFERENT,
        "zzzz definitely not a real agent": ABSENCE_IS_NOT_EVIDENCE,
    }
    every = (
        NO_EXACT_MATCH_BUT_CANDIDATES,
        SIMILARLY_SPELLED_POSSIBLY_DIFFERENT,
        ABSENCE_IS_NOT_EVIDENCE,
    )
    for query, expected in cases.items():
        guidance = lookup_interaction(query).guidance
        present = [claim for claim in every if claim in guidance]
        assert present == [expected], (
            f"{query!r} made claims {len(present)}, expected exactly 1"
        )


def test_candidates_are_deterministic_across_calls() -> None:
    """A different list on a repeat call would make the offered choice unreproducible."""
    first = lookup_interaction("grapefruit").suggestions
    second = lookup_interaction("grapefruit").suggestions
    assert first == second
