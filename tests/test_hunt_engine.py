"""Tests for the unified hunt engine recording (no network)."""

import csv
import tempfile
from pathlib import Path

from brandguard.hunt_engine import RunResult, record_run, run_source


def _result(brand="Binance", source="crtsh", when="2026-01-15T10-00-00+00-00"):
    return RunResult(brand, source, when, 2, 1, 0, [
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
    import pytest

    from brandguard.schema import BrandProfile
    with pytest.raises(ValueError):
        run_source(BrandProfile(brand_name="X"), "no_such_source")


def test_watchlist_sweep_isolates_failures(tmp_path, monkeypatch):
    # A watchlist sweep must record successful runs and skip a failing source
    # without aborting the whole sweep.
    import json as _json

    from brandguard import hunt
    from brandguard.hunt_engine import RunResult

    wl = tmp_path / "wl"
    wl.mkdir()
    for name in ("a", "b"):
        (wl / f"{name}.json").write_text(_json.dumps({
            "brand_name": name, "official_domains": [f"{name}.com"],
            "official_publishers": [], "known_official_apps": [], "sector": "x",
        }), encoding="utf-8")

    def fake_run(profile, source, **kw):
        if source == "website":
            raise RuntimeError("throttle")
        return RunResult(profile.brand_name, source, "2026-01-01T00-00-00+00-00", 1, 0, 0, [])

    monkeypatch.setattr(hunt, "run_source", fake_run)
    results = tmp_path / "results"
    monkeypatch.setattr("sys.argv",
        ["hunt", "--watchlist", str(wl), "--source", "play,website", "--results", str(results)])
    hunt.main()

    log = (results / "run_log.csv").read_text(encoding="utf-8-sig")
    # both brands recorded for play, neither for the failing website source
    assert log.count(",play,") == 2
    assert ",website," not in log


def test_domain_rows_split_detected_from_watch():
    # A live lookalike is a detected threat; a generated lookalike is only to
    # watch. Mentions count as neither.
    from brandguard.discovery.website_hunt import DomainFinding, DomainVerdict
    from brandguard.hunt_engine import _domain_rows

    class E:
        def __init__(self, f, prio):
            self.finding, self.priority, self.evidence = f, prio, f.evidence

    findings = [
        E(DomainFinding("brand-login.com", DomainVerdict.LOOKALIKE, 0.9, ["e"], "q", confirmed_live=True), "high"),
        E(DomainFinding("braand.com", DomainVerdict.LOOKALIKE, 0.98, ["e"], "", confirmed_live=False), "low"),
        E(DomainFinding("brand-social.com", DomainVerdict.MENTIONS_BRAND, 0.8, ["e"], "q", confirmed_live=True), "low"),
    ]
    rows, detected, watch = _domain_rows(findings)
    assert detected == 1 and watch == 1 and len(rows) == 3
