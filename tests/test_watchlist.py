"""Tests for the watchlist scan result shape (no network)."""

from unittest.mock import patch

import scripts.legacy.watchlist_scan as ws
from brandguard.schema import AppRecord, BrandProfile, Publisher
from brandguard.triage.adjudicator import RuleAdjudicator

PROFILE = BrandProfile(
    brand_name="Test Bank", official_domains=["test.com"],
    official_publishers=["Test Bank A.S."], known_official_apps=["Test Mobil"],
    sector="banking", official_package_ids=["com.test.app"],
)

RECORDS = [
    AppRecord(app_id="com.test.app", source="google_play_live", name="Test Mobil",
              publisher=Publisher(name="Test Bank A.S.", website="https://test.com", verified=True)),
    AppRecord(app_id="com.fake.test", source="google_play_live", name="Test Bank Giris",
              publisher=Publisher(name="Fake Dev", account_created="2026-08-01"),
              permissions=["READ_SMS", "RECEIVE_SMS"]),
]


def test_scan_brand_produces_timestamped_structured_result():
    with patch.object(ws, "_gather", return_value=RECORDS), \
         patch.object(ws, "get_adjudicator", return_value=RuleAdjudicator()):
        result = ws.scan_brand(PROFILE, "google_play", 4, 5)

    assert result["brand"] == "Test Bank"
    assert result["platform"] == "google_play"
    assert "T" in result["scanned_at"]  # ISO timestamp
    assert result["candidates"] == 2
    assert result["takedown_candidates"] == 1
    labels = {v["label"] for v in result["verdicts"]}
    assert "official" in labels and "impersonation" in labels


def test_slug_is_filesystem_safe():
    assert ws._slug("Garanti BBVA") == "garanti_bbva"
    assert ws._slug("T.C. Ziraat Bankası A.Ş.").replace("_", "").isalnum()
