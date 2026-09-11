"""langgraph_tool.py — the LangGraph/LangChain binding for the interaction lookup.

Deliberately thin, and deliberately separate from `tool.py`.

`tool.py` owns the contract and all three safety properties: an unknown agent is an answer
rather than an exception, the absence-is-not-evidence statement is a field rather than a log
line, and a direction token never travels without the sentence that says which way the level
moves. Those properties are the reviewable part, and they are testable with no framework
installed and no framework version to track.

This module owns only the adapter: a `@tool`-decorated function whose docstring is the prompt
the model reads when deciding whether to call it. Swapping agent frameworks, or upgrading one,
touches this file and cannot reach the safety properties — which is the point of the split.

The import is guarded rather than assumed. `agent_pk.interactions` must stay importable in an
environment that has the numeric core but not the agent stack, because the PK test suite runs
there, so this module is NOT imported by the package `__init__`. Import it explicitly:

    from agent_pk.interactions.langgraph_tool import interaction_lookup_tool
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from agent_pk.interactions.tool import lookup_interaction_json


@tool("interaction_lookup", parse_docstring=False)
def interaction_lookup_tool(agent: str) -> dict[str, Any]:
    """Look up how a drug, food or event affects a patient's tacrolimus blood level.

    Call this whenever the patient mentions ANY new medicine, supplement, food, or illness —
    including over-the-counter products, herbal remedies, grapefruit or pomelo, and symptoms
    such as diarrhoea or vomiting. Call it even when you believe you already know the answer.

    The result tells you the DIRECTION of the effect and the mechanism behind it, with full
    citations. It never tells you the size of the effect, and there is no size in the source
    data: do not state, estimate, or imply how many ng/mL a level will move, do not suggest a
    dose change, and do not predict a level.

    Read `direction_meaning` and use its words. Several entries are counterintuitive — an
    intestinal illness RAISES tacrolimus rather than lowering it, because it damages the gut
    wall that normally breaks the drug down — so never infer the direction from the agent's
    name or from general reasoning about what illness does.

    MATCHING IS EXACT, and the table's names for foods and events are full descriptive phrases
    rather than single words, so a short everyday word often misses. You do NOT need to guess a
    fuller phrase: the tool returns the candidates itself in `suggestions`. Look up a candidate
    only after the PERSON has confirmed which they meant. Never invent a phrase to force a
    match, and never resolve a DRUG name yourself — a near miss onto the wrong drug is worse
    than no answer.

    `found` false has TWO MEANINGS and they are not interchangeable. READ `guidance`, which
    states which one applies, and report it rather than paraphrasing this docstring.
      - `suggestions` NON-EMPTY: there was no EXACT match, but the table holds related entries.
        The agent may well BE in the table under a fuller name. Name the candidates to the
        person and ask which they mean. NEVER pick one yourself, and never report this as the
        agent being absent.
      - `suggestions` EMPTY: nothing close is in the curated table. That is NOT evidence it is
        safe or that it does not interact — the table is a curated subset. Say it is unknown
        here and refer the patient to their transplant team's own interaction check.

    Args:
        agent: The drug, food, supplement or event, as the patient described it.

    Returns:
        A dict with `found`, `direction`, `direction_meaning`, `mechanism`, `strength`,
        `evidence`, `note`, `sources` and `guidance`. Report `guidance` verbatim when you have
        nothing else to say about limits.
    """
    return lookup_interaction_json(agent)
