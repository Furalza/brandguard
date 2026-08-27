"""Tests for the shared schema."""

from datetime import date

import pytest
from pydantic import ValidationError

from brandguard.schema import AppRecord, Evidence, Label, Publisher, Verdict


def _record(**overrides) -> AppRecord:
    base = {
        "app_id": "com.example.app",
        "source": "mock",
        "name": "Example App",
        "publisher": Publisher(name="Example Ltd"),
    }
    base.update(overrides)
    return AppRecord(**base)


def test_missing_optional_fields_are_none_not_zero():
    record = _record()
    assert record.downloads is None
    assert record.permissions == []
    assert record.publisher.account_created is None


def test_downloads_zero_is_preserved_as_observed_value():
    record = _record(downloads=0)
    assert record.downloads == 0


def test_confidence_is_bounded():
    with pytest.raises(ValidationError):
        Verdict(
            app_id="x",
            source="mock",
            label=Label.UNCERTAIN,
            confidence=1.3,
            evidence=[],
        )


def test_analyst_json_matches_brief_shape():
    verdict = Verdict(
        app_id="com.example.fake",
        source="mock",
        label=Label.IMPERSONATION,
        confidence=0.874,
        evidence=[Evidence(signal="name", text="Name uses Cyrillic a", weight=0.4, tier=0)],
        score=0.9,
        tiers_used=[0],
    )
    out = verdict.to_analyst_json()
    assert set(out) == {"app_id", "source", "label", "confidence", "evidence"}
    assert out["label"] == "impersonation"
    assert out["confidence"] == 0.87
    assert out["evidence"] == ["Name uses Cyrillic a"]


def test_dates_parse_from_iso_strings():
    record = _record(published="2024-03-01")
    assert record.published == date(2024, 3, 1)
