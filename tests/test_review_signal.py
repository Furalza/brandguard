"""Tests for the review-consistency signal.

The signal must fire only on the organically implausible pattern (large install
base, tiny review count, near-perfect rating) and abstain on everything else,
including legitimate large apps and small apps with few reviews.
"""

import json
from pathlib import Path

from brandguard.schema import AppRecord, BrandProfile, Publisher
from brandguard.triage.scored_signals import review_consistency_signal

PROFILE = BrandProfile(
    **json.loads(
        (Path(__file__).resolve().parents[1] / "data" / "profiles" / "ornek_bank.json")
        .read_text(encoding="utf-8")
    )
)


def _rec(downloads, reviews, rating):
    return AppRecord(
        app_id="x", source="s", name="X", publisher=Publisher(name="P"),
        downloads=downloads, review_count=reviews, rating=rating,
    )


def test_fires_on_inflated_pattern():
    assert review_consistency_signal(_rec(5_000_000, 30, 5.0), PROFILE) is not None


def test_abstains_on_legitimate_large_app():
    assert review_consistency_signal(_rec(5_000_000, 182_000, 4.3), PROFILE) is None


def test_abstains_on_small_app_with_few_reviews():
    assert review_consistency_signal(_rec(3_000, 12, 5.0), PROFILE) is None


def test_abstains_when_data_missing():
    assert review_consistency_signal(_rec(None, 12, 5.0), PROFILE) is None
    assert review_consistency_signal(_rec(5_000_000, None, 5.0), PROFILE) is None


def test_abstains_when_rating_not_perfect():
    # Few reviews alone is not enough; the rating must also be implausibly high.
    assert review_consistency_signal(_rec(1_000_000, 50, 4.1), PROFILE) is None


def test_signal_is_low_weight():
    sig = review_consistency_signal(_rec(5_000_000, 30, 5.0), PROFILE)
    assert sig.strength <= 0.3  # cannot dominate a decision
