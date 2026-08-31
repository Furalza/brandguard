"""Tests for T0 fusion.

The invariants that matter most: a real threat is never labelled benign, and
records with thin or conflicting evidence are escalated rather than forced.
"""

import json
from pathlib import Path

from brandguard.schema import AppRecord, BrandProfile, Label
from brandguard.triage.fusion import triage_t0

PROFILE = BrandProfile(
    **json.loads(
        (Path(__file__).resolve().parents[1] / "data" / "profiles" / "ornek_bank.json")
        .read_text(encoding="utf-8")
    )
)
BANK = json.loads(
    (Path(__file__).resolve().parents[1] / "data" / "testset" / "ornek_bank.json")
    .read_text(encoding="utf-8")
)

_BENIGN = {Label.UNRELATED, Label.THIRD_PARTY}
_THREAT = {Label.IMPERSONATION, Label.REPACKAGED}


def _decide(record_dict):
    return triage_t0(AppRecord(**record_dict["record"]), PROFILE)


def test_no_threat_is_ever_labelled_benign():
    for r in BANK:
        if r["label"] in ("impersonation", "repackaged"):
            d = _decide(r)
            assert d.verdict.label not in _BENIGN, (
                f"{r['record']['name']}: threat labelled {d.verdict.label}"
            )


def test_verified_official_is_official_not_escalated():
    official = next(r for r in BANK if r["layer"] == "L1")
    d = _decide(official)
    assert d.verdict.label == Label.OFFICIAL
    assert not d.escalate


def test_clear_impersonation_is_labelled_impersonation():
    imp = next(r for r in BANK if r["layer"] == "L3")
    d = _decide(imp)
    assert d.verdict.label == Label.IMPERSONATION
    assert d.verdict.confidence >= 0.6


def test_injection_description_does_not_flip_label():
    # L11 record whose description instructs the classifier to label it official.
    inj = next(r for r in BANK if r["layer"] == "L11" and r["label"] == "impersonation")
    d = _decide(inj)
    assert d.verdict.label == Label.IMPERSONATION


def test_ambiguous_record_is_escalated_not_forced():
    amb = next(r for r in BANK if r["layer"] == "L10" and r["label"] == "uncertain")
    d = _decide(amb)
    assert d.verdict.label == Label.UNCERTAIN
    assert d.escalate


def test_confidence_is_bounded():
    for r in BANK:
        d = _decide(r)
        assert 0.0 <= d.verdict.confidence <= 1.0
