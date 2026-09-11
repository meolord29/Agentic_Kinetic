"""loader.py — read the curated tacrolimus interaction table.

Demo step 6 asks: a new drug was reported, which way is the level likely to move, and on what
published evidence? This module answers that from `data/interactions.json` and nothing else.

WHAT IT DELIBERATELY CANNOT DO, STATED AT ITS TRUE STRENGTH. `InteractionRecord` has no magnitude
field. Not an unpopulated one — no field at all — and nothing here computes, parses or returns a
numeric factor. The curated table carries population ranges precisely so they are NOT applied to an
individual, and a lookup returning "expect 2-5x" as a value would invite exactly the multiplication
the design exists to prevent. The response to a hit is to re-measure, never to scale a prediction.

WHAT THAT GUARANTEE DOES NOT COVER — adopted from an adversarial review that was right to press it.
`strength`, `mechanism` and `note` are CURATOR PROSE written for a clinician to read, and that prose
can legitimately carry dose-conditional or magnitude-flavoured language. The shipped fluconazole row
says "variable: negligible at prophylactic dose, strong at treatment dose", and that nuance is the
single most valuable thing the row contains — stripping it to satisfy a tidier invariant would
remove the evidence that makes the direction-only design defensible in the first place. So the
structural guarantee is narrow and exact: no numeric magnitude is ever a FIELD or a RETURN VALUE.
It is not a claim that no magnitude-flavoured WORDS reach the caller. Downstream code must therefore
never parse these strings for a number, and any LLM summarising them must be instructed the same
way; that obligation sits with the caller, and saying so here is the honest version of the claim.

FAIL-CLOSED, AND WHY IT MATTERS MORE HERE THAN USUAL. Every malformed-data path raises. The
failure this guards against is specific: a table that loads EMPTY, or that silently drops the
records it could not parse, answers "no interaction" for every drug it lost. That is
indistinguishable from a clean result and it fails in the dangerous direction, so there is no
tolerant branch anywhere in the load path.

This is the first module in `agent_pk` to read a file. It is kept out of `agent_pk.pk` for that
reason: the numeric core's testability rests on it being a pure function of its arguments, and
that property is worth protecting. Nothing here touches patient data, the network, or a secret.
"""

from __future__ import annotations

import json
import logging
import unicodedata
from dataclasses import dataclass
from difflib import get_close_matches
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

SUPPORTED_SCHEMA_VERSION: Final = 1
"""The only `schema_version` this loader understands.

Read and enforced, rather than declared and ignored. The data file has carried this field since it
was written and nothing has ever checked it, which makes it decoration: a future format change
would be parsed by today's loader as though it were today's format, surfacing as whatever
downstream confusion the wrong shape happened to cause.
"""

_MAX_SUGGESTIONS: Final = 3
_SUGGESTION_CUTOFF: Final = 0.75
"""Similarity floor for `suggest`. Deliberately high: these are shown to a human to choose from,
and a long list of weak matches is worse than none."""


# ── Errors ───────────────────────────────────────────────────────────────────


class InteractionsError(ValueError):
    """Base class for every failure in this module."""


class InteractionsDataError(InteractionsError):
    """The interaction data file is missing, unreadable, or does not match the expected shape."""


class UnknownAgentError(InteractionsError):
    """The queried agent is not in the curated table.

    Raised rather than returned as `None` on purpose. A `None` return reads naturally as
    `if not result: "no interaction found"`, and that sentence is false — the table is a curated
    subset of a much larger interaction literature. Absence from it is absence of an ENTRY, never
    evidence of absence of an INTERACTION, and the exception message says so at the point of use.
    """


# ── Types ────────────────────────────────────────────────────────────────────


class Direction(StrEnum):
    """Which way a reported agent moves the tacrolimus level.

    The members mirror the data file's own `direction_key` exactly. A value in the file outside
    this set is a load error rather than a skipped record.
    """

    RAISES = "raises"
    LOWERS = "lowers"
    ADDITIVE_HARM = "additive_harm"
    AVOID = "avoid"


@dataclass(frozen=True, slots=True)
class Source:
    """One cited source backing an interaction record.

    Attributes:
        id: The file's own stable identifier for this source.
        citation: Full citation text as curated.
        url: Resolvable link. Present on every source in the file.
    """

    id: str
    citation: str
    url: str


@dataclass(frozen=True, slots=True)
class InteractionRecord:
    """What the curated table says about one agent.

    There is no magnitude field, by design — see the module docstring.

    Attributes:
        agent: The agent's name as written in the table.
        agent_class: Its drug/food/event class, e.g. "azole antifungal".
        mechanism: How it acts on tacrolimus disposition, in the curator's words.
        direction: Which way the level moves.
        strength: The curator's qualitative strength note. Free text rather than an enum
            because at least one entry is deliberately conditional ("variable: negligible at
            prophylactic dose, strong at treatment dose"), and that nuance is the point.
        evidence: Provenance of the claim, e.g. "label", "literature".
        note: Curator's note, or None.
        sources: Full citations resolved from the record's `source_ids`. Empty when the record
            cites none.
    """

    agent: str
    agent_class: str
    mechanism: str
    direction: Direction
    strength: str
    evidence: str
    note: str | None
    sources: tuple[Source, ...]


@dataclass(frozen=True, slots=True)
class InteractionTable:
    """An immutable, validated view of the curated interaction data.

    Built once by `load_table`. Every record was validated at load, so a lookup cannot fail on
    malformed data — only on an agent that is genuinely absent.
    """

    records: tuple[InteractionRecord, ...]
    _by_normalised_name: dict[str, InteractionRecord]

    def contains(self, agent: str) -> bool:
        """Whether the table holds an entry for `agent`, without raising.

        Args:
            agent: Agent name, in any casing or spacing.

        Returns:
            True if an entry exists.
        """
        return _normalise(agent) in self._by_normalised_name

    def lookup(self, agent: str) -> InteractionRecord:
        """Return the curated record for `agent`.

        Args:
            agent: Agent name as reported, in any casing or spacing. Matching is exact after
                conservative normalisation — never fuzzy. A near-miss onto the wrong drug in a
                safety lookup is worse than no answer, so approximate candidates are offered to a
                human via `suggest` and never selected automatically.

        Returns:
            The matching record.

        Raises:
            UnknownAgentError: If no entry exists. The message states that this is not evidence
                of no interaction, and names any close entries for a human to consider.
        """
        key = _normalise(agent)
        record = self._by_normalised_name.get(key)
        if record is not None:
            return record

        close = self.suggest(agent)
        hint = f" Close entries in the table: {', '.join(close)}." if close else ""
        raise UnknownAgentError(
            f"{agent!r} is not in the curated interaction table. This is NOT evidence that it "
            f"does not interact with tacrolimus — the table is a curated subset of the "
            f"interaction literature, and an absent agent is simply unexamined here. Treat it as "
            f"unknown and refer to the transplant team's own interaction check.{hint}"
        )

    def suggest(self, agent: str) -> tuple[str, ...]:
        """Close entry names, for a HUMAN to disambiguate.

        Never used to resolve a lookup automatically. Offered so that an obvious typo can be
        corrected by the person who typed it, rather than guessed at by this module.

        Args:
            agent: The name that failed to match.

        Returns:
            Up to three table names, most similar first. Empty when nothing is close.
        """
        matches = get_close_matches(
            _normalise(agent),
            list(self._by_normalised_name),
            n=_MAX_SUGGESTIONS,
            cutoff=_SUGGESTION_CUTOFF,
        )
        return tuple(self._by_normalised_name[m].agent for m in matches)


# ── Helpers ──────────────────────────────────────────────────────────────────


def default_data_path() -> Path:
    """Resolve the packaged interaction data file.

    Derived from this module's own location rather than written as an absolute or home-anchored
    path, so the repository stays relocatable and no host fact is inlined.

    Returns:
        Path to `data/interactions.json` at the project root.
    """
    return Path(__file__).resolve().parents[3] / "data" / "interactions.json"


def _normalise(name: str) -> str:
    """Casefold and collapse whitespace for exact matching.

    Conservative on purpose: Unicode NFKC, casefold, and whitespace collapse. No stemming, no
    fuzzy distance, no brand-to-generic mapping — the data file carries no alias field, so any
    such mapping would be invented here rather than curated, which is the failure mode this
    project has already corrected once.

    Args:
        name: Raw agent name.

    Returns:
        Normalised key.
    """
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


def _require_str(
    raw: dict[str, Any], key: str, where: str, *, optional: bool = False
) -> Any:
    """Read a string field, raising rather than defaulting when it is absent or the wrong type.

    Args:
        raw: The record being parsed.
        key: Field name.
        where: Human-readable location, used in the error message.
        optional: When True, a missing field yields None instead of raising.

    Returns:
        The string value, or None when optional and absent.

    Raises:
        InteractionsDataError: If the field is absent (and not optional) or not a string.
    """
    if key not in raw:
        if optional:
            return None
        raise InteractionsDataError(f"{where}: required field {key!r} is missing")
    value = raw[key]
    if not isinstance(value, str):
        raise InteractionsDataError(
            f"{where}: field {key!r} must be a string, got {type(value).__name__}"
        )
    return value


def _parse_sources(raw: object, where: str) -> dict[str, Source]:
    """Parse and index the file's `sources` list.

    Args:
        raw: The value of the top-level `sources` key.
        where: Location label for error messages.

    Returns:
        Sources keyed by their declared id.

    Raises:
        InteractionsDataError: If the list is malformed or an id is duplicated.
    """
    if not isinstance(raw, list):
        raise InteractionsDataError(f"{where}: 'sources' must be a list")
    by_id: dict[str, Source] = {}
    for index, item in enumerate(raw):
        loc = f"{where}: sources[{index}]"
        if not isinstance(item, dict):
            raise InteractionsDataError(f"{loc} must be an object")
        source = Source(
            id=_require_str(item, "id", loc),
            citation=_require_str(item, "citation", loc),
            url=_require_str(item, "url", loc),
        )
        if source.id in by_id:
            raise InteractionsDataError(f"{loc}: duplicate source id {source.id!r}")
        by_id[source.id] = source
    return by_id


def _parse_record(
    raw: object, index: int, name_key: str, sources: dict[str, Source], where: str
) -> InteractionRecord:
    """Parse one entry from the file into a validated record.

    Args:
        raw: The entry object.
        index: Its position, for error messages.
        name_key: Which field names this record — 'agent', 'item' or 'event', since the file
            uses a different key per section.
        sources: Sources available for `source_ids` resolution.
        where: Section label for error messages.

    Returns:
        The validated record.

    Raises:
        InteractionsDataError: On any malformed or unrecognised field. Nothing is skipped: a
            record this loader cannot parse would otherwise vanish from the table and read as
            'no interaction' for that agent.
    """
    loc = f"{where}[{index}]"
    if not isinstance(raw, dict):
        raise InteractionsDataError(f"{loc} must be an object")

    direction_raw = _require_str(raw, "direction", loc)
    try:
        direction = Direction(direction_raw)
    except ValueError as exc:
        raise InteractionsDataError(
            f"{loc}: unrecognised direction {direction_raw!r}. Known directions are "
            f"{sorted(d.value for d in Direction)}. Refusing to load rather than skip this "
            f"record: a dropped entry answers 'no interaction' for that agent."
        ) from exc

    source_ids = raw.get("source_ids", [])
    if not isinstance(source_ids, list):
        raise InteractionsDataError(f"{loc}: 'source_ids' must be a list")
    resolved: list[Source] = []
    for source_id in source_ids:
        if not isinstance(source_id, str):
            raise InteractionsDataError(f"{loc}: source id must be a string")
        if source_id not in sources:
            raise InteractionsDataError(
                f"{loc}: cites unknown source id {source_id!r}. A dangling citation is worse "
                f"than none in a table whose whole purpose is to be citable."
            )
        resolved.append(sources[source_id])

    return InteractionRecord(
        agent=_require_str(raw, name_key, loc),
        agent_class=_require_str(raw, "class", loc, optional=True) or "",
        mechanism=_require_str(raw, "mechanism", loc),
        direction=direction,
        strength=_require_str(raw, "strength", loc),
        evidence=_require_str(raw, "evidence", loc),
        note=_require_str(raw, "note", loc, optional=True),
        sources=tuple(resolved),
    )


def _parse_expected_counts(data: dict[str, Any], where: str) -> dict[str, int]:
    """Read the file's own declaration of how many records each section should hold.

    This exists because presence-and-non-emptiness alone cannot detect PARTIAL loss: an edit that
    deletes twenty of forty-one drugs leaves a section that is present, non-empty, and wrong. A
    declared count turns that into a load error.

    It is deliberately a maintenance burden. Adding a drug means updating the number, which forces
    whoever edits a clinical reference table to state that they meant to change its size.

    Args:
        data: The parsed top-level object.
        where: Location label for error messages.

    Returns:
        Section name to declared count.

    Raises:
        InteractionsDataError: If the declaration is absent, malformed, or holds a non-integer.
    """
    raw = data.get("expected_record_counts")
    if raw is None:
        raise InteractionsDataError(
            f"{where}: 'expected_record_counts' is missing. Without it, a partial deletion loads "
            f"silently as a smaller curated table."
        )
    if not isinstance(raw, dict):
        raise InteractionsDataError(
            f"{where}: 'expected_record_counts' must be an object"
        )
    counts: dict[str, int] = {}
    for section, value in raw.items():
        # bool subclasses int, so this order matters: `isinstance(True, int)` is True.
        if isinstance(value, bool) or not isinstance(value, int):
            raise InteractionsDataError(
                f"{where}: expected_record_counts[{section!r}] must be an integer, got {value!r}"
            )
        if value < 1:
            raise InteractionsDataError(
                f"{where}: expected_record_counts[{section!r}] must be at least 1"
            )
        counts[section] = value
    return counts


# ── Core logic ───────────────────────────────────────────────────────────────


def load_table(path: Path | None = None) -> InteractionTable:
    """Load and validate the curated interaction table.

    Every section of the file is parsed — drugs, foods and physiological events — because a
    patient reporting grapefruit or diarrhoea is reporting the same kind of event as a patient
    reporting a new antifungal, and step 6 must answer all three.

    Args:
        path: Data file to read. Defaults to the packaged `data/interactions.json`.

    Returns:
        A validated, immutable table.

    Raises:
        InteractionsDataError: If the file is missing, unreadable, not valid UTF-8, not valid
            JSON, declares an unsupported schema version, or contains any record this loader
            cannot fully parse. There is no tolerant path.
    """
    resolved_path = default_data_path() if path is None else path

    try:
        text = resolved_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InteractionsDataError(
            f"cannot read the interaction table at {resolved_path}: {type(exc).__name__}. "
            f"Refusing to continue with an empty table, which would answer 'no interaction' "
            f"for every drug."
        ) from exc
    except UnicodeDecodeError as exc:
        # Not an OSError — it subclasses ValueError, so the branch above never sees it.
        raise InteractionsDataError(
            f"the interaction table at {resolved_path} is not valid UTF-8"
        ) from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InteractionsDataError(
            f"the interaction table at {resolved_path} is not valid JSON: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise InteractionsDataError(f"{resolved_path}: top level must be an object")

    version = data.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise InteractionsDataError(
            f"{resolved_path}: 'schema_version' must be an integer, got {version!r}"
        )
    if version != SUPPORTED_SCHEMA_VERSION:
        raise InteractionsDataError(
            f"{resolved_path}: schema_version {version} is not supported by this loader "
            f"(expected {SUPPORTED_SCHEMA_VERSION})"
        )

    expected = _parse_expected_counts(data, str(resolved_path))

    if "sources" not in data:
        raise InteractionsDataError(
            f"{resolved_path}: required section 'sources' is missing"
        )
    sources = _parse_sources(data["sources"], str(resolved_path))

    records: list[InteractionRecord] = []
    section_counts: dict[str, int] = {"sources": len(sources)}
    for section, name_key in (
        ("entries", "agent"),
        ("foods", "item"),
        ("physiological_events", "event"),
    ):
        # `.get(section, [])` would make a DELETED section indistinguishable from an empty one,
        # and an empty one indistinguishable from a curated absence — the silent-loss failure this
        # module exists to prevent. Presence is required; emptiness is an error.
        if section not in data:
            raise InteractionsDataError(
                f"{resolved_path}: required section {section!r} is missing. Refusing to load a "
                f"partial table: every agent in a dropped section would answer as though it had "
                f"simply never been curated."
            )
        raw_section = data[section]
        if not isinstance(raw_section, list):
            raise InteractionsDataError(f"{resolved_path}: {section!r} must be a list")
        if not raw_section:
            raise InteractionsDataError(
                f"{resolved_path}: section {section!r} is empty. An empty section is a curated "
                f"table that lost its contents, which is indistinguishable from a clean result "
                f"at every call site."
            )
        for index, raw_record in enumerate(raw_section):
            records.append(
                _parse_record(
                    raw_record, index, name_key, sources, f"{resolved_path}:{section}"
                )
            )
        section_counts[section] = len(raw_section)

    for section, declared in sorted(expected.items()):
        actual = section_counts.get(section)
        if actual is None:
            raise InteractionsDataError(
                f"{resolved_path}: 'expected_record_counts' declares unknown section {section!r}"
            )
        if actual != declared:
            raise InteractionsDataError(
                f"{resolved_path}: section {section!r} holds {actual} records but "
                f"'expected_record_counts' declares {declared}. Either records were lost, or the "
                f"declaration was not updated when they were added. Both are edit errors and "
                f"neither is safe to guess at."
            )
    missing_declarations = sorted(set(section_counts) - set(expected))
    if missing_declarations:
        raise InteractionsDataError(
            f"{resolved_path}: 'expected_record_counts' does not declare {missing_declarations}. "
            f"Every section must be counted, or partial loss in an undeclared one is invisible."
        )

    by_name: dict[str, InteractionRecord] = {}
    for record in records:
        key = _normalise(record.agent)
        if key in by_name:
            raise InteractionsDataError(
                f"{resolved_path}: duplicate entry {record.agent!r} after normalisation — "
                f"a lookup could not resolve it unambiguously"
            )
        by_name[key] = record

    logger.info(
        "loaded %d interaction records and %d sources from %s",
        len(records),
        len(sources),
        resolved_path,
    )
    return InteractionTable(records=tuple(records), _by_normalised_name=by_name)
