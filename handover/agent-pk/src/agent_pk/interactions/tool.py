"""tool.py — the interaction lookup as an agent tool, framework-agnostic.

`loader.py` answers the question. This module decides what an AGENT is allowed to be told, and
in what shape, which is a different question with different failure modes.

Three properties this boundary has to preserve, each of which was a real defect somewhere in
this project before it was a rule here:

**An unknown agent is an ANSWER, not an error.** `InteractionTable.lookup` raises
`UnknownAgentError`, which is right for a Python caller. Raising at a tool boundary is not: a
language model that receives an exception retries, rephrases, or fills the gap from its own
weights — and the gap it would be filling is a drug-interaction claim. So absence is returned as
a successful result whose payload says, in words the model will carry forward, that the table is
a curated subset and that an absent agent is unexamined rather than safe.

**A disclosure has to survive the boundary it crosses.** The loader states "this is NOT evidence
that it does not interact" inside an exception message. An exception message that is caught and
converted to `found: false` has been thrown away. The statement therefore travels as a FIELD of
the result, not as prose the caller may or may not have logged.

**A direction token is not a direction.** `raises` means the tacrolimus level goes UP, which for
several entries in this table is the counterintuitive answer — diarrhoea RAISES tacrolimus by
damaging the gut wall that normally metabolises it, which reads backwards to anyone reasoning
from "illness lowers things". A model handed the bare token `raises` alongside the word
`diarrhoea` has everything it needs to say the opposite. Every result therefore carries an
explicit sentence naming which way the level moves and why that matters, and the model is never
asked to expand an enum member on its own.

The module holds no framework import on purpose. A LangGraph `@tool` binding is a wrapper around
`lookup_interaction`; keeping the contract here means it is testable without the framework, and
that swapping or adding a framework never touches the safety properties above.
"""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_pk.interactions.loader import (
    Direction,
    InteractionRecord,
    InteractionTable,
    Source,
    UnknownAgentError,
    load_table,
)

logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

_MAX_CANDIDATES = 5
"""Cap on offered candidates. A long list is not a choice, it is a prompt to guess."""


DIRECTION_MEANING: dict[Direction, str] = {
    Direction.RAISES: (
        "This RAISES the tacrolimus blood level. The level goes UP, which moves the patient "
        "toward the toxic edge of the range, where the drug damages the kidney it is "
        "protecting."
    ),
    Direction.LOWERS: (
        "This LOWERS the tacrolimus blood level. The level goes DOWN, which moves the patient "
        "toward the under-immunosuppressed edge, where the immune system can attack the graft "
        "without any symptom the patient would notice."
    ),
    Direction.ADDITIVE_HARM: (
        "This does not necessarily move the tacrolimus level itself. It adds harm on top of "
        "tacrolimus by acting on the same organ — most often the kidney — so the combination is "
        "worse than either alone even when the level looks unchanged."
    ),
    Direction.AVOID: (
        "This combination is one the sources say to avoid rather than to monitor. The concern "
        "is not a level to watch but a pairing not to make."
    ),
}
"""Plain-English meaning of each direction, written for a model to carry verbatim.

Keyed on the enum rather than looked up by string so that adding a `Direction` member without a
meaning is caught at import by `_check_direction_meanings_complete`, not at the first patient who
reports that agent. Same reasoning as the channel module's import-time mapping check."""

ABSENCE_IS_NOT_EVIDENCE: str = (
    "This agent is NOT in the curated interaction table. That is not evidence that it does not "
    "interact with tacrolimus — the table is a curated subset of the interaction literature, and "
    "an agent that is absent from it is simply unexamined here, not established as safe. Treat "
    "it as UNKNOWN and say so. Refer the patient to their transplant team's own interaction "
    "check, which is the authoritative source."
)
"""Carried on every not-found result.

The loader states this inside an exception message. An exception that is caught and turned into
`found: false` has discarded it, and `found: false` on its own is read as "no interaction" by
almost any reader, human or model. So it is a field."""

SIMILARLY_SPELLED_POSSIBLY_DIFFERENT: str = (
    "There is no entry under that name, and nothing in the curated table CONTAINS that name. "
    "The entries named in `suggestions` are merely SPELLED SIMILARLY and may be entirely "
    "DIFFERENT agents — a different drug with a similar name is exactly what this case looks "
    "like. Do NOT treat them as related, do NOT ask 'did you mean X', and do NOT look one up "
    "on your own initiative. Report that the name as given is not in the table, show the "
    "similar names only so a PERSON can spot their own typo, and refer to the transplant "
    "team's own interaction check."
)
"""The third shape of not-found, and it exists because the second one overstated a relationship.

ADOPTED FROM A DECORRELATED SECOND-LINEAGE REVIEW (s9, Stage B, MEDIUM), against the first
reviewer, which had rated the same case LOW. The witness: "nimodipine" is not in the table,
"nifedipine" is, they are DIFFERENT DRUGS, and containment cannot pair them — only edit distance
reaches across. Yet the candidate branch told the model the table "holds one or more closely
related entries" that the agent "may well BE in the table" under.

That is a false statement about a clinical safety table — the same KIND of defect as the finding
that produced this branch in the first place, reintroduced on the branch built to fix it. The
second reviewer's argument for the upgrade is the one that decided it: the model is told not to
pick, but a warm relatedness label is precisely what makes a near-miss confirmation — "did you
mean nifedipine?" — the natural next turn, and a person who typed a drug name will often say yes.

So relatedness is now asserted ONLY where it was actually established, by whole-word containment.
Edit-distance neighbours are named as what they are: possible typos of something else."""


NO_EXACT_MATCH_BUT_CANDIDATES: str = (
    "There is no EXACT entry under that name, but the curated table holds one or more closely "
    "related entries, named below in `suggestions`. Do NOT pick one yourself. Name them to the "
    "person and ask which they mean, then look that name up. The table's food and event entries "
    "are written as full descriptive phrases, so a short everyday word often will not match "
    "even when the thing itself IS in the table."
)
"""Used INSTEAD of ABSENCE_IS_NOT_EVIDENCE when containment candidates exist.

ADOPTED FROM AN ADVERSARIAL REVIEW (s9, Stage A, HIGH), and the distinction is the whole
finding. The absence text asserts that the agent is not in the table. For a query like
"grapefruit" that assertion is FACTUALLY FALSE — the table holds "grapefruit and grapefruit
juice" — so the result was not merely unhelpful, it stated something untrue about a clinical
safety table and then wrapped it in a disclaimer that made it read as careful.

A truthful not-found therefore has two shapes, and the code must not use one for the other:
nothing close is known, or nothing matched EXACTLY. Only the first may claim absence."""


DIRECTIONAL_NOT_DIAGNOSTIC: str = (
    "This table gives the DIRECTION of an interaction, never its size. It does not predict a "
    "concentration, it does not adjust a dose, and it does not replace a blood level. Report "
    "the direction and the mechanism; never state or imply a magnitude, a new dose, or a "
    "predicted level."
)
"""Carried on every result, found or not.

There is no magnitude field in the source data by design. A model that is handed a direction and
a mechanism, with no instruction against it, will readily supply a plausible magnitude — and a
fabricated magnitude in this domain is a dosing claim."""


def _check_direction_meanings_complete() -> None:
    """Refuse to import if any Direction member lacks a plain-English meaning.

    Import-time rather than call-time for the same reason `channel.views` checks its own
    mapping at import: a member added without a meaning would otherwise surface as a KeyError
    on the first patient who reports that agent, which is both the worst moment to find it and
    the one least likely to be covered by a test.

    Raises:
        RuntimeError: If a member is unmapped.
    """
    missing = [d.value for d in Direction if d not in DIRECTION_MEANING]
    if missing:
        raise RuntimeError(
            f"Direction members with no entry in DIRECTION_MEANING: {missing}. Every direction "
            f"a lookup can return must carry a sentence a model can repeat, because the bare "
            f"enum token is what gets inverted."
        )


_check_direction_meanings_complete()


# ── Types ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CitedSource:
    """One citation, in the shape a tool result carries it.

    A projection of `loader.Source` rather than a re-use of it, so that widening what the loader
    holds internally is not automatically a decision to show it to a model.

    Attributes:
        citation: Full citation text as curated.
        url: Resolvable link.
    """

    citation: str
    url: str

    def as_dict(self) -> dict[str, str]:
        """Plain-JSON form.

        Returns:
            A dict of str to str.
        """
        return {"citation": self.citation, "url": self.url}


@dataclass(frozen=True, slots=True)
class InteractionLookupResult:
    """What the agent is told about one reported agent.

    Both outcomes — found and not-found — are instances of this type rather than an exception on
    one branch, so that a caller cannot handle the found case and forget the other.

    Attributes:
        queried: The name exactly as it was passed in, so a model can echo what it searched
            rather than the table's spelling of it.
        found: Whether the curated table holds an entry.
        agent: The table's own name for the agent. None when not found.
        agent_class: Drug/food/event class. None when not found.
        direction: The direction token, e.g. "raises". None when not found.
        direction_meaning: Which way the level moves, in a sentence. None when not found.
        mechanism: How it acts, in the curator's words. None when not found.
        strength: The curator's qualitative strength note, deliberately free text — at least one
            entry is conditional on dose, and that nuance is the point. None when not found.
        evidence: Provenance of the claim, e.g. "label", "literature". None when not found.
        note: Curator's note, where there is one.
        sources: Full citations. Empty when the record cites none, or when not found.
        suggestions: Close entries in the table, for a HUMAN to disambiguate. Never resolved
            automatically — a near-miss onto the wrong drug is worse than no answer.
        guidance: The statement the caller must carry forward. On a not-found result this is
            the absence-is-not-evidence text; on every result it includes the
            directional-not-diagnostic constraint.
    """

    queried: str
    found: bool
    guidance: str
    agent: str | None = None
    agent_class: str | None = None
    direction: str | None = None
    direction_meaning: str | None = None
    mechanism: str | None = None
    strength: str | None = None
    evidence: str | None = None
    note: str | None = None
    sources: tuple[CitedSource, ...] = ()
    suggestions: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """Plain-JSON form, for a tool boundary that must serialise.

        Every value is a str, bool, None, or a list of those — no dataclasses and no StrEnum
        members, both of which serialise inconsistently or not at all depending on the encoder.

        Returns:
            A JSON-serialisable dict.
        """
        return {
            "queried": self.queried,
            "found": self.found,
            "guidance": self.guidance,
            "agent": self.agent,
            "agent_class": self.agent_class,
            "direction": self.direction,
            "direction_meaning": self.direction_meaning,
            "mechanism": self.mechanism,
            "strength": self.strength,
            "evidence": self.evidence,
            "note": self.note,
            "sources": [s.as_dict() for s in self.sources],
            "suggestions": list(self.suggestions),
        }


# ── Table access ─────────────────────────────────────────────────────────────

_TABLE: InteractionTable | None = None


def _table(path: Path | None = None) -> InteractionTable:
    """Return the interaction table, loading it at most once per process.

    Loaded lazily rather than at import so that a malformed data file fails the first LOOKUP
    with a clear error rather than making the module unimportable — which would also break the
    test suite's ability to exercise the malformed-file cases. A caller passing an explicit
    `path` always gets a fresh load and never touches the cache, which is what the tests need.

    Args:
        path: Explicit data file. None uses the packaged default and the cache.

    Returns:
        A validated table.

    Raises:
        InteractionsDataError: If the data file is malformed. Fail-closed: there is no branch
            that yields an empty table, because an empty table answers "no interaction" for
            every agent, which is both wrong and wrong in the dangerous direction.
    """
    if path is not None:
        return load_table(path)
    global _TABLE
    if _TABLE is None:
        _TABLE = load_table()
    return _TABLE


def _project_sources(sources: tuple[Source, ...]) -> tuple[CitedSource, ...]:
    """Project loader sources into the tool's own citation type.

    Args:
        sources: Sources as the loader resolved them.

    Returns:
        The tool-facing projection.
    """
    return tuple(CitedSource(citation=s.citation, url=s.url) for s in sources)


def _tokens(name: str) -> frozenset[str]:
    """Normalised word tokens of an agent name, for CONTAINMENT only.

    Deliberately cruder than the loader's matching key and used for a deliberately weaker
    purpose. Punctuation becomes whitespace so that "star fruit (carambola)" yields the tokens
    a person would type, and everything is casefolded through NFKC so a query differing only in
    case or spacing tokenises identically.

    Args:
        name: Raw agent name.

    Returns:
        The set of word tokens.
    """
    folded = unicodedata.normalize("NFKC", name).casefold()
    cleaned = "".join(ch if ch.isalnum() else " " for ch in folded)
    return frozenset(cleaned.split())


def _candidates(
    table: InteractionTable, agent: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Table entries a HUMAN should be asked about, when nothing matched exactly.

    Two sources, unioned: deterministic TOKEN CONTAINMENT (every word of the query appears in
    the entry's name, or vice versa), and the loader's own edit-distance `suggest`.

    THIS IS NOT FUZZY MATCHING AND MUST NEVER BECOME IT. Nothing here resolves a lookup: the
    result stays `found=False` and these names are offered for a person to choose between. The
    loader's rule stands — a near miss onto the wrong DRUG is worse than no answer — and
    containment is what lets "grapefruit" surface "grapefruit and grapefruit juice" without
    letting "nifedipine" surface "nimodipine", because containment requires whole words rather
    than similar spelling.

    Ordering is deterministic — containment hits first, shortest name first, then alphabetically
    — so the same query yields the same list on every run and in every process.

    Args:
        table: The loaded interaction table.
        agent: The name that failed to match exactly.

    Returns:
        `(contained, similar)`. `contained` are entries that genuinely CONTAIN the query as
        whole words — relatedness is established, and only these may be described as related.
        `similar` are edit-distance neighbours with no shared whole word — possible typos of a
        DIFFERENT agent, and describing them as related is the defect a second-lineage review
        raised. Both empty is the ONLY case that may claim the agent is absent from the table.
    """
    query = _tokens(agent)
    if not query:
        return (), ()
    contained: list[str] = []
    for record in table.records:
        entry = _tokens(record.agent)
        if query <= entry or entry <= query:
            contained.append(record.agent)
    contained.sort(key=lambda name: (len(name), name))

    similar = [n for n in table.suggest(agent) if n not in contained]
    return tuple(contained[:_MAX_CANDIDATES]), tuple(similar[:_MAX_CANDIDATES])


def _found_result(queried: str, record: InteractionRecord) -> InteractionLookupResult:
    """Build the result for an agent that IS in the table.

    Args:
        queried: The name as passed in.
        record: The matching curated record.

    Returns:
        A populated result carrying the direction, its meaning, and every citation.
    """
    return InteractionLookupResult(
        queried=queried,
        found=True,
        guidance=DIRECTIONAL_NOT_DIAGNOSTIC,
        agent=record.agent,
        agent_class=record.agent_class,
        direction=record.direction.value,
        direction_meaning=DIRECTION_MEANING[record.direction],
        mechanism=record.mechanism,
        strength=record.strength,
        evidence=record.evidence,
        note=record.note,
        sources=_project_sources(record.sources),
    )


# ── The tool ─────────────────────────────────────────────────────────────────


def lookup_interaction(
    agent: str, *, data_path: Path | None = None
) -> InteractionLookupResult:
    """Look up what the curated table says about one drug, food or event.

    This is the function an agent framework binds as a tool. It does not raise on an unknown
    agent: absence is a first-class answer, because a raised exception at a tool boundary is an
    invitation for a language model to answer from its own weights instead, and the thing it
    would be answering is a drug-interaction question.

    Args:
        agent: The agent's name as the patient reported it, in any casing or spacing. Matching
            is exact after conservative normalisation, never fuzzy.
        data_path: Explicit interaction data file. None uses the packaged default.

    Returns:
        An `InteractionLookupResult`. `found` distinguishes the two cases; both carry `guidance`,
        and the not-found case carries the absence-is-not-evidence statement plus any close
        entries for a human to consider.

    Raises:
        InteractionsDataError: If the interaction data file itself is malformed. This is a
            deployment defect rather than a runtime condition, and it fails closed — a caller
            must not be handed a table that silently lost records.
        ValueError: If `agent` is not a non-empty string.
    """
    if not isinstance(agent, str) or not agent.strip():
        raise ValueError("agent must be a non-empty string")

    table = _table(data_path)
    try:
        record = table.lookup(agent)
    except UnknownAgentError:
        contained, similar = _candidates(table, agent)
        suggestions = contained + similar
        # THREE shapes of not-found, and each may claim only what its evidence supports:
        # relatedness where containment established it, a typo warning where only the spelling
        # is close, and absence only where nothing at all is near.
        if contained:
            claim = NO_EXACT_MATCH_BUT_CANDIDATES
        elif similar:
            claim = SIMILARLY_SPELLED_POSSIBLY_DIFFERENT
        else:
            claim = ABSENCE_IS_NOT_EVIDENCE
        logger.info(
            "interaction lookup: %r no exact match (%d contained, %d similarly spelled)",
            agent,
            len(contained),
            len(similar),
        )
        return InteractionLookupResult(
            queried=agent,
            found=False,
            guidance=f"{claim} {DIRECTIONAL_NOT_DIAGNOSTIC}",
            suggestions=suggestions,
        )

    logger.info(
        "interaction lookup: %r matched %r (%s)",
        agent,
        record.agent,
        record.direction.value,
    )
    return _found_result(agent, record)


def lookup_interaction_json(
    agent: str, *, data_path: Path | None = None
) -> dict[str, Any]:
    """`lookup_interaction`, returning the plain-JSON form a tool boundary needs.

    The convenience a framework binding actually wants: most tool decorators serialise the
    return value, and a frozen dataclass is not reliably serialisable across encoders.

    Args:
        agent: The agent's name as the patient reported it.
        data_path: Explicit interaction data file. None uses the packaged default.

    Returns:
        A JSON-serialisable dict.

    Raises:
        InteractionsDataError: If the interaction data file is malformed.
        ValueError: If `agent` is not a non-empty string.
    """
    return lookup_interaction(agent, data_path=data_path).as_dict()
