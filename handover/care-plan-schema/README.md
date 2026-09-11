# Care Plan Schema — design notes

A home-care agent that lives in the household's own group chat. It does not diagnose,
and it does not decide anything. A clinician has already written a plan with thresholds
in it; the agent's whole job is to notice when reality drifts from that plan and say so,
to the right person, in time.

## The invariant

**No threshold originates with the agent.** Every rule carries `cites`, pointing at an
entry in the plan's own `sources`. A rule without a citation cannot be authored — the
schema requires `minItems: 1` — so an invented threshold is a validation failure rather
than a judgement call.

## Where the model is allowed to act

    observer's own words  ──►  extraction model  ──►  typed observation
                                                            │
                                                            ▼
                                              deterministic rule evaluation
                                                            │
                                                            ▼
                                                  escalation + evidence

The language model normalises. It turns "she slept all afternoon again" into
`daytime_sleep_hours: 4`. **It never evaluates a rule and never fires an escalation.**
Predicates are a closed structure (`all` / `any` / `not` / `test`) over a closed set of
operators; `metric` resolves only to a declared observation or derivation. No string is
ever evaluated as an expression.

`agent_authority` bounds output per rule:

| value | the agent may |
|---|---|
| `observe_only` | record, and route to a human |
| `inform` | state what was observed and what the plan says happens next |
| `instruct_within_plan` | state one action, and only the exact wording in `permitted_action` |

Anything else routes. This is what keeps the agent on the safe side of medical advice:
the only instruction it can give is one a clinician wrote into the plan.

## Safety properties worth naming

**Silence is a state.** Every observation declares `missing_after_hours`. Past that it is
`stale`, and `is_stale` is a testable condition. No answer never reads as normal.

**An unanswered escalation promotes.** Any escalation with `requires_ack` must declare
`ack_timeout_minutes` and `on_timeout_escalate_to`. A human who does not reply is not a
handled escalation, and the ladder climbs on its own until someone acknowledges or it
reaches emergency.

**A plan is not evaluable until it is complete.** `activation.state` gates everything, and
any `required` open question disables the rules it `blocks`. Unanswered questions are not
a gap in a document — they are named, addressed to a specific clinician, and mechanically
suppress the rules that depend on them.

**Escalations are written for their reader.** `message` is three required parts: the
`ask` first in ordinary words, then `because`, then `if_ignored`. No identifier appears
before the plain sentence.

**Disclosure is role-scoped.** `may_receive` decides what each role sees; an observer can
receive observations and escalations without clinical detail.

**On-call, not "the family".** A role with `on_call_rota: true` is whoever is on call now.
Escalations addressed to a person who is asleep in another time zone do not get answered.

## Cadences

The plan declares its own review rhythm rather than leaving it to habit: daily capture,
a weekly household review, a monthly evidence refresh, a quarterly pack for the clinician.
Each names the role it is produced for.

## Worked examples

| plan | why it is here |
|---|---|
| `transplant-tacrolimus` | Strictest possible adherence protocol, no lifestyle component. Non-adherence carries roughly seven times the graft-loss risk, and the first undetectable drug level arrives a median of about three years before the graft is lost — a long, silent, observable window. |
| `dapt-stent` | The failure is *coordination*, not adherence: a dentist or surgeon tells the patient to stop, not knowing a stent is healing. The hero rule has `cooldown_hours: 0` by design. |
| `hepatic-encephalopathy` | The patient loses the ability to report her own decline, and the observer is a layperson. The only example using `instruct_within_plan`, and it is blocked until the clinic supplies its titration card. |

## Validation

Two gates, both must pass:

1. JSON Schema (2020-12) — shape.
2. Referential integrity — every `collected_by`, `metric`, `escalate_to`, `cites`,
   `route_to`, `on_timeout_escalate_to` and `blocks` resolves; every ack has a promotion
   target; no plan is `active` while a required question still blocks a rule.

The second gate caught a real authoring error on first run — an open question that blocked
an escalation id where a rule id was required. Shape validation alone would have passed it.

## Not built here

The extraction model, the chat transport, the scheduler, and the evidence store. This
directory is the contract between them, drafted before build day and declarable as prior
work. All clinical content is synthetic; the two `PLACEHOLDER` sources stand where a real
deployment carries the issuing unit's own document.
