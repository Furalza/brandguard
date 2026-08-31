"""Run the full evaluation over all brand test sets and print the report.

Uses the deterministic RuleAdjudicator so numbers are reproducible run to run;
the live model is validated separately with scripts/run_cascade.py (see K-024).

    python scripts/evaluate.py
"""

from __future__ import annotations

import json
from pathlib import Path

from brandguard.eval.dataset import load_testset
from brandguard.eval.metrics import (
    Prediction,
    calibration_table,
    confusion_matrix,
    missed_threat_rate,
    per_class_prf,
    takedown_false_positive_rate,
    tier_usage,
)
from brandguard.schema import BrandProfile, Label
from brandguard.triage.adjudicator import RuleAdjudicator
from brandguard.triage.fusion import triage_t0
from brandguard.triage.tier2 import triage_t2


def collect_predictions() -> list[Prediction]:
    adjudicator = RuleAdjudicator()
    preds: list[Prediction] = []
    for profile_path in sorted(Path("data/profiles").glob("*.json")):
        profile = BrandProfile(**json.loads(profile_path.read_text(encoding="utf-8")))
        testset = Path("data/testset") / profile_path.name
        if not testset.exists():
            continue
        for item in load_testset(testset):
            decision = triage_t0(item.record, profile)
            if decision.escalate or decision.verdict.label == Label.UNCERTAIN:
                decision = triage_t2(item.record, profile, decision, adjudicator)
            preds.append(Prediction(
                gold=item.label,
                predicted=decision.verdict.label,
                confidence=decision.verdict.confidence,
                tiers_used=tuple(decision.verdict.tiers_used),
                reason=decision.reason,
            ))
    return preds


def main() -> None:
    preds = collect_predictions()

    print(f"records evaluated: {len(preds)}\n")

    print("== Takedown false-positive rate (brief constraint: < 5%) ==")
    fp = takedown_false_positive_rate(preds)
    print(f"flagged as takedown: {fp['flagged']}, false among them: {fp['false']}, "
          f"rate: {fp['rate']:.1%}\n")

    print("== Missed threats (threat labelled benign) ==")
    mt = missed_threat_rate(preds)
    print(f"threats: {mt['threats']}, missed: {mt['missed']}, rate: {mt['rate']:.1%}\n")

    print("== Per-class precision / recall ==")
    print(f"{'class':<24}{'precision':>10}{'recall':>8}{'support':>9}{'predicted':>11}")
    for label, row in per_class_prf(preds).items():
        print(f"{label.value:<24}{row['precision']:>10}{row['recall']:>8}"
              f"{row['support']:>9}{row['predicted']:>11}")
    print()

    print("== Confusion matrix (rows: gold, cols: predicted) ==")
    labels = list(Label)
    header = "".join(f"{lbl.value[:10]:>11}" for lbl in labels)
    print(f"{'':<24}{header}")
    matrix = confusion_matrix(preds)
    for gold in labels:
        row = matrix.get(gold, {})
        cells = "".join(f"{row.get(pred, 0):>11}" for pred in labels)
        print(f"{gold.value:<24}{cells}")
    print()

    print("== Calibration (stated vs actual accuracy per confidence bin) ==")
    for row in calibration_table(preds):
        print(f"bin {row['bin']}  n={row['n']:<3} stated={row['stated']:<6} actual={row['actual']}")
    print()

    print("== Tier usage (cost) ==")
    usage = tier_usage(preds)
    print(f"t0-only: {usage['t0_only']}, t1: {usage['t1']}, t2: {usage['t2']} "
          f"({usage['t2_share']:.0%} of records)")


if __name__ == "__main__":
    main()
