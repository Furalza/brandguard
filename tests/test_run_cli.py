"""Tests for the end-to-end run() entry point."""

import json
from pathlib import Path

from brandguard.schema import BrandProfile
from brandguard.triage.adjudicator import RuleAdjudicator
from run import _load_records, run

ROOT = Path(__file__).resolve().parents[1]
PROFILE = BrandProfile(
    **json.loads((ROOT / "data" / "profiles" / "ornek_bank.json").read_text(encoding="utf-8"))
)
RECORDS = _load_records(ROOT / "data" / "testset" / "ornek_bank.json")


def test_run_produces_brief_shaped_verdicts():
    verdicts = run(PROFILE, RECORDS, adjudicator=RuleAdjudicator())
    assert len(verdicts) == len(RECORDS)
    for v in verdicts:
        assert set(v) == {"app_id", "source", "label", "confidence", "evidence"}
        assert isinstance(v["evidence"], list)
        assert 0.0 <= v["confidence"] <= 1.0


def test_run_labels_are_all_valid():
    valid = {"official", "impersonation", "repackaged",
             "third_party_legitimate", "unrelated", "uncertain"}
    for v in run(PROFILE, RECORDS, adjudicator=RuleAdjudicator()):
        assert v["label"] in valid


def test_loader_accepts_plain_records(tmp_path):
    plain = [{
        "app_id": "com.x.y", "source": "mock", "name": "Test",
        "publisher": {"name": "Dev"},
    }]
    path = tmp_path / "plain.json"
    path.write_text(json.dumps(plain), encoding="utf-8")
    records = _load_records(path)
    assert len(records) == 1 and records[0].app_id == "com.x.y"
