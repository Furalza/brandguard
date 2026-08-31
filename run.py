"""BrandGuard command-line entry point.

Takes a brand profile and a set of candidate records, runs the full triage
cascade, and prints analyst-facing verdicts. This is the single command a user
runs; everything else is a library.

    python run.py --profile data/profiles/ornek_bank.json \
                  --records data/testset/ornek_bank.json

Records may be the evaluation format (objects with a "record" field and a gold
"label") or a plain list of AppRecord objects. Gold labels, if present, are
ignored here; use scripts/evaluate.py to score against them.

Output is a JSON array of verdicts in the shape the brief specifies:
{app_id, source, label, confidence, evidence}. Add --pretty for a table.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from brandguard.schema import AppRecord, BrandProfile, Label
from brandguard.triage.adjudicator import get_adjudicator
from brandguard.triage.fusion import triage_t0
from brandguard.triage.tier1 import triage_t1
from brandguard.triage.tier2 import triage_t2


def _load_records(path: Path) -> list[AppRecord]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    records = []
    for item in raw:
        payload = item["record"] if isinstance(item, dict) and "record" in item else item
        records.append(AppRecord(**payload))
    return records


def run(
    profile: BrandProfile,
    records: list[AppRecord],
    official_icon: str | None = None,
    adjudicator=None,
) -> list[dict]:
    """Run the full cascade over records and return analyst JSON verdicts.

    ``adjudicator`` may be injected (tests, offline runs); when omitted it is
    selected from the environment by ``get_adjudicator``.
    """
    adjudicator = adjudicator or get_adjudicator()
    verdicts = []
    for record in records:
        decision = triage_t0(record, profile)
        if decision.escalate:
            decision = triage_t1(record, profile, decision, official_icon)
        if decision.escalate or decision.verdict.label == Label.UNCERTAIN:
            decision = triage_t2(record, profile, decision, adjudicator)
        verdicts.append(decision.verdict.to_analyst_json())
    return verdicts


def main() -> None:
    parser = argparse.ArgumentParser(description="BrandGuard impersonation triage.")
    parser.add_argument("--profile", required=True, type=Path, help="brand profile JSON")
    parser.add_argument("--records", required=True, type=Path, help="candidate records JSON")
    parser.add_argument("--official-icon", type=Path, default=None, help="path to the official icon")
    parser.add_argument("--pretty", action="store_true", help="print a table instead of JSON")
    parser.add_argument(
        "--only", choices=[label.value for label in Label], default=None,
        help="print only verdicts with this label",
    )
    args = parser.parse_args()

    profile = BrandProfile(**json.loads(args.profile.read_text(encoding="utf-8")))
    records = _load_records(args.records)
    icon = str(args.official_icon) if args.official_icon else None

    verdicts = run(profile, records, icon)
    if args.only:
        verdicts = [v for v in verdicts if v["label"] == args.only]

    if args.pretty:
        _print_table(verdicts)
    else:
        json.dump(verdicts, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")


def _print_table(verdicts: list[dict]) -> None:
    print(f"{'label':<24}{'conf':<7}app_id")
    print("-" * 72)
    for v in verdicts:
        print(f"{v['label']:<24}{v['confidence']:<7}{v['app_id']}")
        for line in v["evidence"]:
            print(f"    - {line}")
    print("-" * 72)
    print(f"{len(verdicts)} verdicts")


if __name__ == "__main__":
    main()
