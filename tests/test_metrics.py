"""Tests for evaluation metrics, using small hand-built prediction sets."""

from brandguard.eval.metrics import (
    Prediction,
    calibration_table,
    missed_threat_rate,
    per_class_prf,
    takedown_false_positive_rate,
    tier_usage,
)
from brandguard.schema import Label


def _p(gold, pred, conf=0.9, tiers=(0,), reason="scored"):
    return Prediction(gold=gold, predicted=pred, confidence=conf,
                      tiers_used=tiers, reason=reason)


def test_takedown_fp_counts_only_flagged_records():
    preds = [
        _p(Label.IMPERSONATION, Label.IMPERSONATION),
        _p(Label.THIRD_PARTY, Label.IMPERSONATION),   # the harmful error
        _p(Label.UNRELATED, Label.UNRELATED),
    ]
    fp = takedown_false_positive_rate(preds)
    assert fp == {"flagged": 2, "false": 1, "rate": 0.5}


def test_missed_threats_excludes_uncertain():
    preds = [
        _p(Label.IMPERSONATION, Label.UNCERTAIN),     # deferred, not missed
        _p(Label.IMPERSONATION, Label.THIRD_PARTY),   # missed
        _p(Label.REPACKAGED, Label.REPACKAGED),
    ]
    mt = missed_threat_rate(preds)
    assert mt["threats"] == 3 and mt["missed"] == 1


def test_prf_handles_empty_classes_without_division_error():
    preds = [_p(Label.OFFICIAL, Label.OFFICIAL)]
    rows = per_class_prf(preds)
    assert rows[Label.UNRELATED] == {
        "precision": 0.0, "recall": 0.0, "support": 0, "predicted": 0,
    }


def test_calibration_bins_compare_stated_to_actual():
    preds = [
        _p(Label.OFFICIAL, Label.OFFICIAL, conf=0.9),
        _p(Label.OFFICIAL, Label.UNRELATED, conf=0.9),
    ]
    rows = calibration_table(preds, bins=5)
    row = next(r for r in rows if r["bin"] == "0.8-1.0")
    assert row["n"] == 2 and row["actual"] == 0.5


def test_tier_usage_partitions_records():
    preds = [
        _p(Label.OFFICIAL, Label.OFFICIAL, tiers=(0,)),
        _p(Label.OFFICIAL, Label.OFFICIAL, tiers=(0, 1)),
        _p(Label.OFFICIAL, Label.OFFICIAL, tiers=(0, 2)),
    ]
    usage = tier_usage(preds)
    assert usage["t0_only"] == 1 and usage["t1"] == 1 and usage["t2"] == 1
