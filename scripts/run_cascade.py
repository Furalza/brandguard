"""Run the full cascade live over a brand's evaluation records.

This is the out-of-tests way to exercise the system end to end:

    python scripts/run_cascade.py data/profiles/ornek_bank.json

With an API key in the environment or .env, T2 uses the real model and the
banner names the provider; without one it falls back to the deterministic rule
adjudicator, so the command works everywhere. Gold labels from the evaluation
set are shown next to the system's output so a human can eyeball agreement.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from brandguard.schema import AppRecord, BrandProfile
from brandguard.triage.adjudicator import get_adjudicator
from brandguard.triage.fusion import triage_t0
from brandguard.triage.tier2 import triage_t2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("--json", action="store_true", help="emit analyst JSON instead of a table")
    args = parser.parse_args()

    profile = BrandProfile(**json.loads(args.profile.read_text(encoding="utf-8")))
    testset_path = Path("data/testset") / args.profile.name
    records = json.loads(testset_path.read_text(encoding="utf-8"))

    adjudicator = get_adjudicator()
    print(f"adjudicator: {type(adjudicator).__name__}\n")

    t2_calls = 0
    started = time.perf_counter()
    outputs = []
    for item in records:
        record = AppRecord(**item["record"])
        decision = triage_t0(record, profile)
        if decision.escalate or decision.verdict.label.value == "uncertain":
            decision = triage_t2(record, profile, decision, adjudicator)
            t2_calls += 1
        outputs.append((item, decision))

    elapsed = time.perf_counter() - started

    if args.json:
        print(json.dumps(
            [d.verdict.to_analyst_json() for _, d in outputs],
            ensure_ascii=False, indent=2,
        ))
    else:
        agree = 0
        print(f"{'gold':<24}{'system':<24}{'conf':<6}{'reason':<20}name")
        print("-" * 100)
        for item, decision in outputs:
            gold = item["label"]
            got = decision.verdict.label.value
            mark = "" if gold == got else "  <-- differs"
            if gold == got:
                agree += 1
            print(
                f"{gold:<24}{got:<24}{decision.verdict.confidence:<6}"
                f"{decision.reason:<20}{item['record']['name'][:32]}{mark}"
            )
        print("-" * 100)
        print(
            f"agreement {agree}/{len(outputs)}  |  T2 calls {t2_calls}"
            f"  |  total {elapsed:.2f}s  |  per record {1000 * elapsed / len(outputs):.0f}ms"
        )


if __name__ == "__main__":
    main()
