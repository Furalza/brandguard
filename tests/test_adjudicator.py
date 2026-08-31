"""Tests for the T2 adjudicator: injection safety, opinion dampening, cascade."""

import json
from dataclasses import asdict
from pathlib import Path

from brandguard.schema import AppRecord, BrandProfile, Label
from brandguard.triage.adjudicator import (
    RuleAdjudicator,
    build_case_summary,
    opinion_as_signal,
)
from brandguard.triage.fusion import triage_t0
from brandguard.triage.tier2 import triage_t2

ROOT = Path(__file__).resolve().parents[1]
PROFILE = BrandProfile(
    **json.loads((ROOT / "data" / "profiles" / "ornek_bank.json").read_text(encoding="utf-8"))
)
BANK = json.loads(
    (ROOT / "data" / "testset" / "ornek_bank.json").read_text(encoding="utf-8")
)


def test_case_summary_never_contains_attacker_text():
    # Injection records carry hostile instructions in the description. The case
    # summary must reduce them to booleans; no attacker sentence may survive.
    for r in BANK:
        if r["layer"] != "L11":
            continue
        rec = AppRecord(**r["record"])
        case = build_case_summary(rec, PROFILE, [])
        serialized = json.dumps(asdict(case), ensure_ascii=False).lower()
        for hostile in ("etiketle", "ignore all previous", "official olarak", "onaylanmistir"):
            assert hostile not in serialized, f"attacker text leaked: {hostile!r}"


def test_official_claim_becomes_boolean_fact():
    inj = next(r for r in BANK if r["layer"] == "L11" and r["label"] == "impersonation")
    case = build_case_summary(AppRecord(**inj["record"]), PROFILE, [])
    assert case.description_claims_official is True


def test_injection_cannot_flip_cascade_outcome():
    # Both injection records must keep their true nature through T0->T2.
    adj = RuleAdjudicator()
    for r in BANK:
        if r["layer"] != "L11":
            continue
        rec = AppRecord(**r["record"])
        d = triage_t0(rec, PROFILE)
        if d.escalate:
            d = triage_t2(rec, PROFILE, d, adj)
        if r["label"] == "impersonation":
            assert d.verdict.label == Label.IMPERSONATION
        else:
            # the reverse injection (legit tool asking to be flagged) must not
            # become a takedown label
            assert d.verdict.label not in (Label.IMPERSONATION, Label.REPACKAGED)


def test_adjudicator_signal_is_dampened():
    # Even a fully confident opinion converts to at most 0.5 strength, so the
    # adjudicator alone cannot cross the impersonation threshold.
    from brandguard.triage.adjudicator import AdjudicatorOpinion
    opinion = AdjudicatorOpinion(leaning="impersonation", strength=1.0, reasoning="x")
    signal = opinion_as_signal(opinion)
    assert signal.strength <= 0.5
    assert signal.tier == 2


def test_t2_settles_benign_split():
    # A record the cheap tiers left uncertain, whose facts read third-party,
    # should be settled by the adjudicator's benign leaning.
    adj = RuleAdjudicator()
    settled = 0
    for r in BANK:
        rec = AppRecord(**r["record"])
        d = triage_t0(rec, PROFILE)
        if not d.escalate:
            continue
        d2 = triage_t2(rec, PROFILE, d, adj)
        assert not d2.escalate  # T2 is final
        if d2.reason == "adjudicated_benign":
            settled += 1
    assert settled >= 1


def test_benign_settle_blocked_by_sensitive_permissions():
    # The apkmirror mirror record carries READ_CONTACTS and no publisher data.
    # Even a benign adjudicator leaning must not settle it; evidence-absence
    # uncertainty is not resolvable by language judgement.
    from brandguard.triage.adjudicator import AdjudicatorOpinion

    class BenignAdjudicator:
        def adjudicate(self, case):
            return AdjudicatorOpinion(
                leaning=Label.THIRD_PARTY.value, strength=0.9, reasoning="benign"
            )

    mirror = next(
        r for r in BANK if r["layer"] == "L10" and r["record"]["source"] == "apkmirror"
    )
    rec = AppRecord(**mirror["record"])
    d0 = triage_t0(rec, PROFILE)
    d2 = triage_t2(rec, PROFILE, d0, BenignAdjudicator())
    assert d2.verdict.label == Label.UNCERTAIN
