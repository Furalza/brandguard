"""Tests for the unified hunt engine recording (no network)."""

import csv
import tempfile
from pathlib import Path

from brandguard.hunt_engine import RunResult, record_run, run_source


def _result(brand="Binance", source="crtsh", when="2026-01-15T10-00-00+00-00"):
    return RunResult(brand, source, when, 2, 1, [
        {"domain": "binance-login.com", "verdict": "lookalike", "similarity": 0.95,
         "priority": "high", "confirmed_live": True, "evidence": ["x"]},
    ])


def test_record_writes_timestamped_json_and_log():
    tmp = Path(tempfile.mkdtemp())
    path = record_run(_result(), tmp)
    assert path.exists()
    assert "binance" in path.name.lower() and "crtsh" in path.name
    log = (tmp / "run_log.csv").read_text(encoding="utf-8-sig")
    assert "Binance" in log and "crtsh" in log


def test_two_runs_are_separate_comparable_files():
    tmp = Path(tempfile.mkdtemp())
    p1 = record_run(_result(when="2026-01-15T10-00-00+00-00"), tmp)
    p2 = record_run(_result(when="2026-01-16T10-00-00+00-00"), tmp)
    assert p1.name != p2.name
    rows = list(csv.reader((tmp / "run_log.csv").open(encoding="utf-8-sig")))
    assert len(rows) == 3  # header + two runs


def test_unknown_source_rejected():
    from brandguard.schema import BrandProfile
    import pytest
    with pytest.raises(ValueError):
        run_source(BrandProfile(brand_name="X"), "no_such_source")
