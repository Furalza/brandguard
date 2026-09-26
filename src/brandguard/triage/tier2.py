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
    AdjudicatorOpinion,
    build_case_summary,
    get_adjudicator,
    opinion_as_signal,
)
from brandguard.triage.fusion import Decision, _decide_from_signals
from brandguard.triage.reader import build_case_text, reading_evidence
from brandguard.triage.scored_signals import collect_signals


def _ask(adjudicator: Adjudicator, case, record: AppRecord, profile: BrandProfile) -> AdjudicatorOpinion:
    """Prefer the text reader (K-078) when the adjudicator offers one."""
    read = getattr(adjudicator, "read", None)
    if callable(read):
        return read(case, build_case_text(record, profile))
    return adjudicator.adjudicate(case)


def _with_reading(decision: Decision, opinion: AdjudicatorOpinion) -> Decision:
    """Append the reader's analyst lines (weightless) to a decision."""
    if opinion.reading is None:
        return decision
    extra = reading_evidence(opinion.reading)
    if not extra:
        return decision
    verdict = decision.verdict.model_copy(update={"evidence": [*decision.verdict.evidence, *extra]})
    return Decision(verdict=verdict, escalate=decision.escalate, reason=decision.reason)


def triage_t2(
    record: AppRecord,
    profile: BrandProfile,
    prior: Decision,
    adjudicator: Adjudicator | None = None,
) -> Decision:
    """Resolve a still-undecided record with the adjudicator's help."""
    if not prior.escalate and prior.verdict.label != Label.UNCERTAIN:
        return prior  # decided earlier; spend nothing
    # An "uncertain" that T0 did not flag for escalation (a score just under
    # the grey band, K-078) is still undecided: the whole point of T2 is to
    # settle what the rules could not, so it is read too.

    adjudicator = adjudicator or get_adjudicator()
    case = build_case_summary(record, profile, prior.verdict.conflicts)
    try:
        opinion = _ask(adjudicator, case, record, profile)
    except Exception as exc:  # noqa: BLE001 - a model outage must not abort a scan
        # The adjudicator is one signal among many. When it is unreachable the
        # honest outcome is "no opinion": the record keeps whatever the
        # deterministic layer can say and the failure is written into the
        # evidence so the analyst (and the run log) can see the model was down.
        opinion = AdjudicatorOpinion(
            leaning=Label.UNCERTAIN.value, strength=0.0,
            reasoning=f"adjudicator unavailable ({type(exc).__name__})",
        )

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
                "confidence": 0.55,
                "tiers_used": [0, 2],
            }
        )
        return _with_reading(Decision(verdict=verdict, escalate=False, reason="adjudicated_benign"), opinion)

    if decision.escalate:
        # Final answer is uncertain; stop escalating.
        return _with_reading(Decision(verdict=decision.verdict, escalate=False, reason="final_uncertain"), opinion)

    return _with_reading(decision, opinion)
