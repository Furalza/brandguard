"""Tests for veto signals, including the impersonation-name attack."""

import json
from pathlib import Path

from brandguard.schema import AppRecord, BrandProfile, Label, Publisher
from brandguard.triage.veto import check_vetoes

PROFILE = BrandProfile(
    **json.loads(
        (Path(__file__).resolve().parents[1] / "data" / "profiles" / "ornek_bank.json")
        .read_text(encoding="utf-8")
    )
)


def _rec(publisher: Publisher, app_id: str = "com.x.y", name: str = "Örnek Bank Mobil") -> AppRecord:
    return AppRecord(app_id=app_id, source="mock", name=name, publisher=publisher)


def test_verified_official_publisher_vetoes_official():
    rec = _rec(Publisher(name="Örnek Bank A.Ş.", verified=True), app_id="tr.com.ornekbank.mobil")
    v = check_vetoes(rec, PROFILE)
    assert v is not None and v.forced_label == Label.OFFICIAL


def test_flattened_official_name_with_verifier_still_vetoes():
    rec = _rec(Publisher(name="Ornek Bank A.S", website="https://www.ornekbank.com.tr"),
               app_id="tr.com.ornekbank.mobil")
    v = check_vetoes(rec, PROFILE)
    assert v is not None and v.forced_label == Label.OFFICIAL


def test_impersonator_spoofing_publisher_name_is_not_vetoed():
    # The attack: name matches the flattened official publisher, but no verifier.
    rec = _rec(Publisher(name="Ornek Bank A.S", verified=False, website=None),
               app_id="com.ornekbamk.mobile", name="Оrnek Bank Mobil")
    assert check_vetoes(rec, PROFILE) is None


def test_official_package_under_foreign_publisher_is_repackaged():
    rec = _rec(Publisher(name="ModApps", verified=False), app_id="tr.com.ornekbank.mobil")
    v = check_vetoes(rec, PROFILE)
    assert v is not None and v.forced_label == Label.REPACKAGED


def test_no_veto_for_unrelated_publisher():
    rec = _rec(Publisher(name="Some Studio"), app_id="com.game.x", name="Örnek Oyun")
    assert check_vetoes(rec, PROFILE) is None
