"""Tests for query expansion.

The measurable property is coverage: the generated queries must surface the
impersonation and repackaged listings in the evaluation set when run against a
simple substring model of marketplace search.
"""

import json
from pathlib import Path

from brandguard.discovery.normalize import normalize
from brandguard.discovery.query_expansion import expand

TESTSET = Path(__file__).resolve().parents[1] / "data" / "testset" / "ornek_bank.json"
BRAND = "Örnek Bank"


def test_exact_brand_is_first_query():
    queries = expand(BRAND)
    assert queries[0].term == BRAND
    assert queries[0].strategy == "exact"


def test_queries_are_deduplicated():
    terms = [q.term.lower() for q in expand(BRAND)]
    assert len(terms) == len(set(terms))


def test_core_strategies_present():
    # For a brand whose name already contains Turkish characters, the "turkish"
    # variant collapses onto the exact brand and is deduplicated away. The other
    # strategies always contribute.
    strategies = {q.strategy for q in expand(BRAND)}
    assert {"homoglyph", "typosquat", "leet", "multigraph", "suffix", "spacing"} <= strategies


def test_turkish_strategy_contributes_for_ascii_brand():
    # An ASCII brand name yields genuine Turkish-character variants.
    strategies = {q.strategy for q in expand("Hizli Kargo")}
    assert "turkish" in strategies


def test_output_is_bounded():
    # A handful of dozens, not thousands.
    assert len(expand(BRAND)) < 80


def _surfaces(listing_name: str, queries: list[str]) -> bool:
    ln = normalize(listing_name)
    return any(q in ln or ln in q for q in queries)


def test_coverage_of_impersonations_is_complete():
    queries = [normalize(q.term) for q in expand(BRAND)]
    bank = json.loads(TESTSET.read_text(encoding="utf-8"))
    targets = [r for r in bank if r["label"] in ("impersonation", "repackaged")]
    surfaced = [r for r in targets if _surfaces(r["record"]["name"], queries)]
    assert len(surfaced) == len(targets), (
        f"missed: {[r['record']['name'] for r in targets if r not in surfaced]}"
    )


def test_multigraph_substitution_generates_variant():
    # "Örnek" contains "rn"; collapsing it to "m" yields "omek", a real attack.
    terms = {q.term for q in expand(BRAND)}
    assert "omek bank" in terms
