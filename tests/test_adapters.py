"""Tests for source adapters and parsing helpers.

The point of these tests is that three very different source schemas all produce
the same normalized AppRecord shape, and that missing fields stay None.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from brandguard.discovery.adapters import get_adapter, normalize_records
from brandguard.discovery.parsing import parse_date, parse_downloads, split_permissions

MOCK = Path(__file__).resolve().parents[1] / "data" / "mock_markets"


@pytest.mark.parametrize(
    "value,expected",
    [(1000, 1000), ("1,000+", 1000), ("1K", 1000), ("2.5M", 2_500_000),
     (0, 0), (None, None), ("abc", None), ("", None), (True, None)],
)
def test_parse_downloads(value, expected):
    assert parse_downloads(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [("2024-03-01", date(2024, 3, 1)), ("2024-03-01T10:00:00Z", date(2024, 3, 1)),
     (1709251200, date(2024, 3, 1)), (None, None), ("2 weeks ago", None)],
)
def test_parse_date(value, expected):
    assert parse_date(value) == expected


def test_split_permissions_strips_prefix_and_uppercases():
    assert split_permissions(["android.permission.READ_SMS", "camera"]) == ["READ_SMS", "CAMERA"]
    assert split_permissions("READ_SMS; CAMERA") == ["READ_SMS", "CAMERA"]
    assert split_permissions(None) == []


def test_all_three_sources_produce_apprecord():
    for source in ("google_play", "nested_store", "thirdparty_apk"):
        raw = json.loads((MOCK / f"{source}.json").read_text(encoding="utf-8"))
        records = normalize_records(source, raw)
        assert records
        for r in records:
            assert r.source == source
            assert r.app_id and r.name and r.publisher.name != "" or r.source == "thirdparty_apk"


def test_nested_store_epoch_date_parsed():
    raw = json.loads((MOCK / "nested_store.json").read_text(encoding="utf-8"))
    record = normalize_records("nested_store", raw)[0]
    assert record.publisher.account_created == date(2025, 2, 14)
    assert record.downloads == 20000
    assert record.permissions == ["READ_SMS", "RECEIVE_SMS", "READ_CONTACTS"]


def test_thirdparty_missing_signals_are_none():
    raw = json.loads((MOCK / "thirdparty_apk.json").read_text(encoding="utf-8"))
    record = normalize_records("thirdparty_apk", raw)[0]
    # This source provides no rating, review count, or publisher metadata.
    assert record.rating is None
    assert record.review_count is None
    assert record.publisher.account_created is None
    assert record.downloads == 3200  # but downloads it does provide


def test_unknown_source_raises():
    with pytest.raises(ValueError):
        get_adapter("no_such_store")
