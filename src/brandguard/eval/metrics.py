"""Evaluation metrics for the cascade.

Everything the brief asks the evaluation to answer lives here:

- a six-class confusion matrix (which class is mistaken for which),
- per-class precision and recall,
- the takedown false-positive rate, which is the constraint the brief caps at
  5%: of the records the system labels impersonation or repackaged, how many are
  actually neither,
- calibration bins (when the system says 0.9, is it right about 90% of the
  time), reported as a table because with a small set a curve would overstate
  the resolution we actually have,
- tier usage, which is the cost report: what share of records each tier decided.

Metrics are pure functions over (gold, predicted) pairs so they can be tested
in isolation and reused by any runner.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from brandguard.schema import Label

TAKEDOWN_LABELS = {Label.IMPERSONATION, Label.REPACKAGED}


@dataclass(frozen=True)
class Prediction:
    """One evaluated record: gold label, predicted label, confidence, tier data."""

    gold: Label
    predicted: Label
    confidence: float
    tiers_used: tuple[int, ...]
    reason: str


def confusion_matrix(preds: list[Prediction]) -> dict[Label, Counter]:
    """rows: gold label, columns: predicted label, cells: counts."""
    matrix: dict[Label, Counter] = defaultdict(Counter)
    for p in preds:
        matrix[p.gold][p.predicted] += 1
    return dict(matrix)


def per_class_prf(preds: list[Prediction]) -> dict[Label, dict[str, float | int]]:
    """Precision, recall and support per class.

    Precision: of the records predicted as C, how many are truly C.
    Recall: of the records truly C, how many were predicted C.
    Classes with no predictions or no support report 0.0 rather than dividing
    by zero; support is included so a reader can judge how much a number means.
    """
    out: dict[Label, dict[str, float | int]] = {}
    for label in Label:
        tp = sum(1 for p in preds if p.gold == label and p.predicted == label)
        fp = sum(1 for p in preds if p.gold != label and p.predicted == label)
        fn = sum(1 for p in preds if p.gold == label and p.predicted != label)
        support = tp + fn
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / support if support else 0.0
        out[label] = {
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "support": support,
            "predicted": tp + fp,
        }
    return out


def takedown_false_positive_rate(preds: list[Prediction]) -> dict[str, float | int]:
    """The brief's core constraint.

    Of all records the system would send to an analyst as a takedown candidate
    (impersonation or repackaged), the share whose gold label is neither. This
    is the error that harms a legitimate publisher, so it is measured directly
    rather than derived from per-class numbers.
    """
    flagged = [p for p in preds if p.predicted in TAKEDOWN_LABELS]
    false = [p for p in flagged if p.gold not in TAKEDOWN_LABELS]
    rate = len(false) / len(flagged) if flagged else 0.0
    return {"flagged": len(flagged), "false": len(false), "rate": round(rate, 4)}


def missed_threat_rate(preds: list[Prediction]) -> dict[str, float | int]:
    """The mirror number: true threats the system labelled benign.

    Uncertain does not count as missed; deferring a threat to an analyst is the
    designed behaviour, labelling it unrelated/third_party/official is the
    failure.
    """
    threats = [p for p in preds if p.gold in TAKEDOWN_LABELS]
    benign = {Label.OFFICIAL, Label.THIRD_PARTY, Label.UNRELATED}
    missed = [p for p in threats if p.predicted in benign]
    rate = len(missed) / len(threats) if threats else 0.0
    return {"threats": len(threats), "missed": len(missed), "rate": round(rate, 4)}


def calibration_table(preds: list[Prediction], bins: int = 5) -> list[dict[str, float | int]]:
    """Group predictions by confidence bin and compare stated vs actual accuracy.

    A row like (0.8-1.0, stated 0.93, actual 0.95, n=12) means: for records
    where the system claimed 80-100% confidence, it was right 95% of the time.
    Reported as a table, not a curve: with tens of records, five bins is the
    honest resolution.
    """
    rows = []
    width = 1.0 / bins
    for i in range(bins):
        low, high = i * width, (i + 1) * width
        in_bin = [
            p for p in preds
            if low <= p.confidence < high or (i == bins - 1 and p.confidence == 1.0)
        ]
        if not in_bin:
            continue
        stated = sum(p.confidence for p in in_bin) / len(in_bin)
        actual = sum(1 for p in in_bin if p.gold == p.predicted) / len(in_bin)
        rows.append({
            "bin": f"{low:.1f}-{high:.1f}",
            "n": len(in_bin),
            "stated": round(stated, 3),
            "actual": round(actual, 3),
        })
    return rows


def tier_usage(preds: list[Prediction]) -> dict[str, float | int]:
    """Cost report: how many records each tier had to touch.

    The cascade's economic promise is that most records finish at T0; this
    number is how that promise is checked.
    """
    total = len(preds)
    t2 = sum(1 for p in preds if 2 in p.tiers_used)
    t1 = sum(1 for p in preds if 1 in p.tiers_used and 2 not in p.tiers_used)
    t0_only = total - t1 - t2
    return {
        "total": total,
        "t0_only": t0_only,
        "t1": t1,
        "t2": t2,
        "t2_share": round(t2 / total, 3) if total else 0.0,
    }
