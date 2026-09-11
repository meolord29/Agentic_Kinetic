"""Curated drug, food and physiological interaction lookup for tacrolimus.

Kept separate from `agent_pk.pk` because this subpackage reads a file and the numeric core does
not. That boundary is deliberate: the core's testability rests on being a pure function of its
arguments.
"""

from agent_pk.interactions.loader import (
    SUPPORTED_SCHEMA_VERSION,
    Direction,
    InteractionRecord,
    InteractionsDataError,
    InteractionsError,
    InteractionTable,
    Source,
    UnknownAgentError,
    default_data_path,
    load_table,
)
from agent_pk.interactions.tool import (
    ABSENCE_IS_NOT_EVIDENCE,
    DIRECTION_MEANING,
    DIRECTIONAL_NOT_DIAGNOSTIC,
    NO_EXACT_MATCH_BUT_CANDIDATES,
    SIMILARLY_SPELLED_POSSIBLY_DIFFERENT,
    CitedSource,
    InteractionLookupResult,
    lookup_interaction,
    lookup_interaction_json,
)

__all__ = [
    "ABSENCE_IS_NOT_EVIDENCE",
    "DIRECTIONAL_NOT_DIAGNOSTIC",
    "DIRECTION_MEANING",
    "NO_EXACT_MATCH_BUT_CANDIDATES",
    "SIMILARLY_SPELLED_POSSIBLY_DIFFERENT",
    "CitedSource",
    "InteractionLookupResult",
    "lookup_interaction",
    "lookup_interaction_json",
    "SUPPORTED_SCHEMA_VERSION",
    "Direction",
    "InteractionRecord",
    "InteractionTable",
    "InteractionsDataError",
    "InteractionsError",
    "Source",
    "UnknownAgentError",
    "default_data_path",
    "load_table",
]
