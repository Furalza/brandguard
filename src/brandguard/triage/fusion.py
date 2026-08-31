"""Signal fusion and T0 decision.

Fusion turns a set of signals into a label, a score and a routing decision. It
implements the threat model's precedence:

1. A veto, if present, decides outright.
2. Otherwise signals are combined into a suspicion score in 0..1.
3. The score maps to a label through conservative bands that favour precision:
   the middle is ``uncertain`` rather than a forced call.
4. Records whose signals conflict, or whose score lands in the grey band, are
   flagged for escalation to a higher tier (T1/T2) instead of being decided here.

The score is a bounded combination, not a bare sum: strong agreement should
saturate rather than run away, and a single attacker-controlled signal must not
by itself cross the impersonation threshold. Conflict is detected when both
suspicious and legitimate signals carry real weight.
"""

from __future__ import annotations

from dataclasses import dataclass

from brandguard.discovery.normalize import normalize, tokens
from brandguard.schema import AppRecord, BrandProfile, Evidence, Label, Verdict
from brandguard.triage.scored_signals import collect_signals
from brandguard.triage.signals import Direction, SignalResult
from brandguard.triage.veto import check_vetoes

# Score bands. Deliberately conservative: the impersonation threshold is high and
# the uncertain band is wide, because a false takedown is the costly error.
_IMPERSONATION_THRESHOLD = 0.60
_LEGITIMATE_THRESHOLD = 0.25
_GREY_LOW = 0.35
_GREY_HIGH = 0.60


@dataclass(frozen=True)
class Decision:
    """A T0 decision: a verdict plus whether it should be escalated."""

    verdict: Verdict
    escalate: bool
    reason: str


def _combine(signals: list[SignalResult]) -> float:
    """Combine signal strengths into a suspicion score in 0..1.

    Suspicious signals push up, legitimate ones pull down, using a saturating
    combination so agreement among several weak signals matters but no single
    signal dominates. The result is clamped to 0..1.
    """
    suspicion = 0.0
    for s in signals:
        if s.direction == Direction.SUSPICIOUS:
            # Saturating add: each signal closes part of the remaining gap to 1.
            suspicion += s.strength * (1.0 - suspicion)
    relief = 0.0
    for s in signals:
        if s.direction == Direction.LEGITIMATE:
            relief += s.strength * (1.0 - relief)
    score = suspicion * (1.0 - 0.5 * relief)
    return max(0.0, min(1.0, score))


def _has_conflict(signals: list[SignalResult]) -> bool:
    """True when meaningful suspicious and legitimate signals coexist.

    Both sides must be strong. A weak legitimate signal (a merely non-fresh
    account) does not conflict with a strong suspicious one; that is a suspicious
    record with a neutral-ish account, not a genuine contradiction.
    """
    strong_susp = any(s.direction == Direction.SUSPICIOUS and s.strength >= 0.5 for s in signals)
    strong_legit = any(s.direction == Direction.LEGITIMATE and s.strength >= 0.5 for s in signals)
    return strong_susp and strong_legit


def _benign_label(record: AppRecord, profile: BrandProfile, signals: list[SignalResult]) -> Label:
    """Split a non-suspicious record into unrelated vs third_party.

    The distinction is genuinely semantic (a bank-account aggregator vs a generic
    ATM directory) and cannot be made reliably from attacker-independent fields
    alone; see the investigation in KARARLAR K-016. T0 therefore uses only an
    objective brand relation: does the normalized name or package id contain a
    brand token. No relation at all means search noise (unrelated); a relation
    with no suspicion means a legitimate mention (third_party). The fine call
    carries low confidence and can be escalated.
    """
    brand_toks = set(tokens(profile.brand_name))
    name_toks = set(tokens(record.name))
    pkg = normalize(record.app_id).replace(" ", "")
    related = bool(name_toks & brand_toks) or any(bt in pkg for bt in brand_toks)
    return Label.THIRD_PARTY if related else Label.UNRELATED


def _label_for_score(score: float) -> Label:
    if score >= _IMPERSONATION_THRESHOLD:
        return Label.IMPERSONATION
    if score <= _LEGITIMATE_THRESHOLD:
        return Label.THIRD_PARTY
    return Label.UNCERTAIN


def triage_t0(record: AppRecord, profile: BrandProfile) -> Decision:
    """Run T0: veto, then scored fusion with grey-zone routing."""
    veto = check_vetoes(record, profile)
    if veto is not None:
        verdict = Verdict(
            app_id=record.app_id,
            source=record.source,
            label=veto.forced_label,
            confidence=0.95,
            evidence=[veto.as_evidence()],
            score=1.0 if veto.forced_label == Label.OFFICIAL else 0.9,
            tiers_used=[0],
        )
        return Decision(verdict=verdict, escalate=False, reason="veto")

    signals = collect_signals(record, profile)
    score = _combine(signals)
    conflict = _has_conflict(signals)
    thin = len(signals) <= 1
    any_suspicion = any(
        s.direction == Direction.SUSPICIOUS and s.strength >= 0.4 for s in signals
    )

    # Low score and nothing accusing it: a benign record. Split into unrelated
    # vs third_party by objective brand relation, at low confidence.
    if score <= _LEGITIMATE_THRESHOLD and not any_suspicion and not conflict:
        label = _benign_label(record, profile, signals)
        verdict = Verdict(
            app_id=record.app_id,
            source=record.source,
            label=label,
            confidence=0.65,
            evidence=[s.as_evidence() for s in signals],
            score=round(score, 3),
            tiers_used=[0],
        )
        return Decision(verdict=verdict, escalate=False, reason="benign")

    in_grey = _GREY_LOW <= score < _GREY_HIGH
    escalate = conflict or in_grey or thin

    label = Label.UNCERTAIN if escalate else _label_for_score(score)
    confidence = _confidence(score, label, escalate)

    conflicts = [s.text for s in signals] if conflict else []
    verdict = Verdict(
        app_id=record.app_id,
        source=record.source,
        label=label,
        confidence=confidence,
        evidence=[s.as_evidence() for s in signals],
        score=round(score, 3),
        tiers_used=[0],
        conflicts=conflicts,
    )
    reason = "conflict" if conflict else "grey_zone" if in_grey else "thin_evidence" if thin else "scored"
    return Decision(verdict=verdict, escalate=escalate, reason=reason)


def _confidence(score: float, label: Label, escalate: bool) -> float:
    """Confidence reflects how far the score sits from an uncertain outcome."""
    if escalate or label == Label.UNCERTAIN:
        return round(0.3 + 0.2 * abs(score - 0.475), 3)
    if label == Label.IMPERSONATION:
        return round(min(0.95, 0.6 + (score - _IMPERSONATION_THRESHOLD)), 3)
    return round(min(0.95, 0.6 + (_LEGITIMATE_THRESHOLD - score)), 3)


def to_evidence_list(verdict: Verdict) -> list[Evidence]:
    """Convenience accessor kept for symmetry with the schema."""
    return verdict.evidence
