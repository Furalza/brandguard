"""T2 tier of the cascade.

Runs only for records still undecided after T0/T1. Builds an injection-safe case
summary, asks the adjudicator for an opinion, feeds that opinion back into the
shared fusion rule as one more signal, and resolves the remaining uncertainty.

Two T2-specific rules:

- The adjudicator's leaning can settle the benign semantic split (unrelated vs
  third_party) that K-016 deferred, because that is exactly the language-and-
  context judgement T2 exists for.
- For threat labels the adjudicator remains one dampened signal among many; a
  record with no independent backing still ends uncertain rather than becoming a
  takedown on the model's word alone. The false-positive budget stays with the
  deterministic layer.
"""

from __future__ import annotations

from brandguard.schema import AppRecord, BrandProfile, Label
from brandguard.triage.adjudicator import (
    Adjudicator,
    build_case_summary,
    get_adjudicator,
    opinion_as_signal,
)
from brandguard.triage.fusion import Decision, _decide_from_signals
from brandguard.triage.scored_signals import collect_signals


def triage_t2(
    record: AppRecord,
    profile: BrandProfile,
    prior: Decision,
    adjudicator: Adjudicator | None = None,
) -> Decision:
    """Resolve a still-undecided record with the adjudicator's help."""
    if not prior.escalate:
        return prior  # decided earlier; spend nothing

    adjudicator = adjudicator or get_adjudicator()
    case = build_case_summary(record, profile, prior.verdict.conflicts)
    opinion = adjudicator.adjudicate(case)

    signals = [*collect_signals(record, profile), opinion_as_signal(opinion)]
    decision = _decide_from_signals(record, profile, signals, tier=2)

    # T2 is the last tier: a benign leaning may settle the semantic split
    # whenever the outcome would otherwise stay uncertain. Two kinds of
    # uncertainty must be kept apart here: semantic ambiguity (evidence exists,
    # interpretation is needed) is what a language model can resolve; absence of
    # evidence (no publisher data, no signature) is not, because no amount of
    # reasoning fills a missing fact. As a concrete guard, a record requesting
    # sensitive permissions is never settled benign on the adjudicator's word:
    # a language judgement does not offset a concrete risk marker. Such records
    # end as uncertain, which is the honest answer.
    still_uncertain = decision.escalate or decision.verdict.label == Label.UNCERTAIN
    settle_allowed = not case.sensitive_permissions
    if still_uncertain and settle_allowed and opinion.leaning in (
        Label.UNRELATED.value, Label.THIRD_PARTY.value,
    ):
        verdict = decision.verdict.model_copy(
            update={
                "label": Label(opinion.leaning),
                "confidence": 0.6,
                "tiers_used": [0, 2],
            }
        )
        return Decision(verdict=verdict, escalate=False, reason="adjudicated_benign")

    if decision.escalate:
        # Final answer is uncertain; stop escalating.
        return Decision(verdict=decision.verdict, escalate=False, reason="final_uncertain")

    return decision
