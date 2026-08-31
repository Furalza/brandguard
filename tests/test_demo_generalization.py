"""Generalization check: the cascade behaves correctly on an unseen sector.

These records are not in any training or evaluation set. The test asserts the
safety-critical invariants (no threat labelled benign, no legitimate tool sent
to takedown) rather than exact labels, since some records sit on the benign-
family boundary that only T2 fully resolves.
"""

import json
from pathlib import Path

from brandguard.schema import BrandProfile
from brandguard.triage.adjudicator import RuleAdjudicator
from run import _load_records, run

ROOT = Path(__file__).resolve().parents[1]
PROFILE = BrandProfile(
    **json.loads((ROOT / "data" / "demo" / "kripto_profile.json").read_text(encoding="utf-8"))
)
RECORDS = _load_records(ROOT / "data" / "demo" / "kripto_records.json")

_TAKEDOWN = {"impersonation", "repackaged"}
_BENIGN = {"official", "third_party_legitimate", "unrelated"}


def _verdicts():
    return run(PROFILE, RECORDS, adjudicator=RuleAdjudicator())


def test_official_wallet_is_official():
    # The first record is the official wallet with a verified publisher.
    assert _verdicts()[0]["label"] == "official"


def test_sms_requesting_clone_is_impersonation():
    v = _verdicts()[1]  # fresh-publisher clone with SMS/contacts
    assert v["label"] == "impersonation"
    assert any("crypto" in line for line in v["evidence"])


def test_repackaged_mirror_detected():
    # The last record is an official package id under a mirror publisher.
    assert _verdicts()[-1]["label"] == "repackaged"


def test_no_legitimate_tool_sent_to_takedown():
    # The price tracker and the game must not be flagged for takedown.
    verdicts = _verdicts()
    tracker = next(v for v in verdicts if v["app_id"] == "com.coingecko.tracker")
    game = next(v for v in verdicts if v["app_id"] == "com.oyun.kripto")
    assert tracker["label"] not in _TAKEDOWN
    assert game["label"] not in _TAKEDOWN


def test_airdrop_scam_is_impersonation():
    v = next(v for v in _verdicts() if v["app_id"] == "com.kriptocuzdan.airdrop")
    assert v["label"] == "impersonation"
