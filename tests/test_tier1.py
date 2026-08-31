"""Tests for the T1 tier."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from brandguard.schema import AppRecord, BrandProfile, Label, Publisher
from brandguard.triage.fusion import triage_t0
from brandguard.triage.tier1 import triage_t1

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "data" / "mock_icons"
PROFILE = BrandProfile(
    **json.loads((ROOT / "data" / "profiles" / "ornek_bank.json").read_text(encoding="utf-8"))
)


@pytest.fixture(scope="module", autouse=True)
def _icons():
    if not (ICONS / "official.png").exists():
        subprocess.run([sys.executable, "scripts/make_test_icons.py"], cwd=ROOT, check=True)


def test_t1_passes_through_decided_records():
    # A vetoed record is decided at T0; T1 must not touch it.
    rec = AppRecord(
        app_id="tr.com.ornekbank.mobil", source="mock", name="Örnek Bank Mobil",
        publisher=Publisher(name="Örnek Bank A.Ş.", verified=True),
    )
    t0 = triage_t0(rec, PROFILE)
    assert not t0.escalate
    t1 = triage_t1(rec, PROFILE, t0, str(ICONS / "official.png"))
    assert t1 is t0


def test_t1_adds_icon_evidence_for_escalated_record():
    rec = AppRecord(
        app_id="com.fake.ob", source="mock", name="Örnek Bank Giriş",
        publisher=Publisher(name="Unknown Dev"),
        icon_path=str(ICONS / "near_copy.png"),
    )
    t0 = triage_t0(rec, PROFILE)
    if not t0.escalate:
        pytest.skip("record was decided at T0")
    t1 = triage_t1(rec, PROFILE, t0, str(ICONS / "official.png"))
    signals = [e.signal for e in t1.verdict.evidence]
    assert "icon_similarity" in signals
    assert t1.verdict.tiers_used == [0, 1]


def test_icon_plus_young_account_supports_impersonation():
    # Icon copy alone cannot decide, but with a young account (independent
    # backing) the record should resolve to impersonation.
    rec = AppRecord(
        app_id="com.fake.ob2", source="mock", name="Örnek Bank Güvenli",
        publisher=Publisher(name="New Dev", account_created="2026-08-01"),
        permissions=["READ_SMS", "RECEIVE_SMS"],
        icon_path=str(ICONS / "near_copy.png"),
    )
    t0 = triage_t0(rec, PROFILE)
    t1 = triage_t1(rec, PROFILE, t0, str(ICONS / "official.png"))
    assert t1.verdict.label == Label.IMPERSONATION
